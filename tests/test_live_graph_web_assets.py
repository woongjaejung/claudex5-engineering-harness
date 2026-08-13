from __future__ import annotations

from contextlib import contextmanager
import base64
import json
from pathlib import Path
import re
import subprocess
import threading
import unittest
from urllib.request import urlopen

from scripts.live_graph.sessions import SessionSelection
from scripts.live_graph.web import create_server


ASSET_DIRECTORY = Path(__file__).parents[1] / "scripts" / "live_graph" / "assets"


class MemoryStore:
    def snapshots(self) -> list[dict[str, object]]:
        return []


@contextmanager
def running_server():
    server = create_server(MemoryStore(), SessionSelection.all(), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def run_app_script(script: str) -> dict[str, object]:
    encoded = base64.b64encode((ASSET_DIRECTORY / "app.mjs").read_bytes()).decode("ascii")
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        env={**__import__("os").environ, "APP_URL": f"data:text/javascript;base64,{encoded}"},
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class WebDashboardAssetTests(unittest.TestCase):
    def test_fixed_assets_are_local_and_html_references_only_them(self) -> None:
        expected = {"index.html": "text/html", "style.css": "text/css", "app.mjs": "text/javascript"}
        contents = {name: (ASSET_DIRECTORY / name).read_text(encoding="utf-8") for name in expected}
        self.assertEqual(re.findall(r'(?:href|src)="([^"]+)"', contents["index.html"]), ["data:,", "/style.css", "/app.mjs"])
        self.assertNotIn("<script>", contents["index.html"])
        for content in contents.values():
            self.assertNotRegex(re.sub(r"https?://www\.w3\.org/2000/svg", "", content), r"https?://|//[^\n]*\b(?:analytics|tracking)\b")
        with running_server() as base_url:
            for path, content_type in (("/", expected["index.html"]), ("/style.css", expected["style.css"]), ("/app.mjs", expected["app.mjs"])):
                with self.subTest(path=path), urlopen(base_url + path) as response:
                    self.assertTrue(response.headers["Content-Type"].startswith(content_type))
                    self.assertTrue(response.read())

    def test_view_model_duration_order_and_poll_generation_are_pure(self) -> None:
        rendered = run_app_script("""
          const app = await import(process.env.APP_URL);
          const bundle = {projects:[
            {cwd:'/z/project', running:[{session_id:'run-z', status:'running', title:'Zulu'}], completed:[{session_id:'done-z', status:'passed', title:'Done'}]},
            {cwd:'/a/project', running:[{session_id:'run-a', status:'running', title:'Alpha'}], completed:[]}
          ]};
          console.log(JSON.stringify({
            duration: app.formatDuration('2026-08-14T10:00:00Z', new Date('2026-08-14T11:02:03Z')),
            model: app.buildAllViewModel(bundle, new Date('2026-08-14T11:02:03Z')),
            acceptsFresh: app.canApplyPollResult(7, 7, false),
            rejectsOld: app.canApplyPollResult(7, 6, false),
            rejectsHealthy: app.canApplyPollResult(7, 7, true),
          }));
        """)
        self.assertEqual(rendered["duration"], "01:02:03")
        self.assertEqual([project["cwd"] for project in rendered["model"]["projects"]], ["/a/project", "/z/project"])
        self.assertTrue(rendered["model"]["projects"][1]["completedCollapsed"])
        self.assertEqual(rendered["model"]["projects"][0]["running"][0]["title"], "Alpha")
        self.assertTrue(rendered["acceptsFresh"])
        self.assertFalse(rendered["rejectsOld"])
        self.assertFalse(rendered["rejectsHealthy"])

    def test_transport_keeps_one_stream_falls_back_and_stops_polling_on_sse(self) -> None:
        rendered = run_app_script("""
          const {createTransport} = await import(process.env.APP_URL);
          const jobs = []; let nextId = 0; const applied = []; const status = []; const streams = [];
          const timers = { setTimeout(fn, delay) { const job = {id: ++nextId, fn, delay, cleared:false}; jobs.push(job); return job.id; }, clearTimeout(id) { const job = jobs.find((entry) => entry.id === id); if (job) job.cleared = true; }, setInterval(fn, delay) { return this.setTimeout(fn, delay); }, clearInterval(id) { this.clearTimeout(id); } };
          class Source { constructor(url) { this.url=url; this.listeners={}; this.closed=false; streams.push(this); } addEventListener(name, fn) { this.listeners[name]=fn; } close() { this.closed=true; } }
          const fetches=[]; const fetchImpl=(url) => { fetches.push(url); return Promise.resolve({ok:true, json: async () => ({revision:'poll-1', projects:[]})}); };
          const transport = createTransport({EventSourceImpl:Source, fetchImpl, timers, onBundle:(bundle, meta) => applied.push([bundle.revision, meta.source]), onConnection:(value) => status.push(value), onElapsed:() => status.push('tick')});
          transport.open('selection=all', 4);
          streams[0].listeners.error();
          const failureDelay = jobs.find((job) => job.delay === 5000); failureDelay.fn();
          await Promise.resolve(); await Promise.resolve();
          const retry = jobs.filter((job) => job.delay === 5000 && !job.cleared).at(-1); retry.fn();
          streams[1].listeners.snapshot({data: JSON.stringify({revision:'sse-1', projects:[]})});
          transport.open('session=other', 5);
          console.log(JSON.stringify({urls:streams.map((stream)=>stream.url), firstClosed:streams[0].closed, fallbackFetches:fetches.length, applied, delays:jobs.map((job)=>job.delay), active:transport.state().activeStreams, fallback:transport.state().fallbackPolling, retryCleared:transport.state().retryPending === false, status}));
        """)
        self.assertEqual(rendered["urls"], ["/api/events?selection=all", "/api/events?selection=all", "/api/events?session=other"])
        self.assertTrue(rendered["firstClosed"])
        self.assertEqual(rendered["fallbackFetches"], 1)
        self.assertIn(["poll-1", "poll"], rendered["applied"])
        self.assertIn(["sse-1", "sse"], rendered["applied"])
        self.assertIn(1000, rendered["delays"])
        self.assertEqual(rendered["active"], 1)
        self.assertFalse(rendered["fallback"])
        self.assertTrue(rendered["retryCleared"])

    def test_transport_polls_immediately_without_eventsource_retries_and_rejects_stale_poll(self) -> None:
        rendered = run_app_script("""
          const {createTransport} = await import(process.env.APP_URL);
          const jobs=[]; let serial=0; const applied=[]; const attempts=[];
          const timers = { setTimeout(fn, delay) { const job={id:++serial, fn, delay, cleared:false}; jobs.push(job); return job.id; }, clearTimeout(id) { const job=jobs.find((entry)=>entry.id===id); if(job) job.cleared=true; }, setInterval(fn, delay) { return this.setTimeout(fn, delay); }, clearInterval(id) { this.clearTimeout(id); } };
          const pending=[]; const fetchImpl=(url) => new Promise((resolve) => { attempts.push(url); pending.push(resolve); });
          let Source = undefined;
          function MaybeSource(url) { if (!Source) throw new Error('missing'); return new Source(url); }
          const transport=createTransport({EventSourceImpl:MaybeSource, fetchImpl, timers, onBundle:(bundle, meta)=>applied.push([bundle.revision, meta.generation]), onConnection:()=>{}, onElapsed:()=>{}});
          transport.open('session=a', 1);
          transport.open('session=b', 2);
          pending[0]({ok:true, json:async()=>({revision:'old'})}); await Promise.resolve(); await Promise.resolve();
          class Recovered { constructor(url) { this.url=url; this.listeners={}; globalThis.recovered=this; } addEventListener(name, fn) { this.listeners[name]=fn; } close() {} }
          Source=Recovered; const retry=jobs.find((job)=>job.delay===5000 && !job.cleared); retry.fn(); globalThis.recovered.listeners.snapshot({data:JSON.stringify({revision:'fresh'})});
          console.log(JSON.stringify({attempts, applied, delays:jobs.map((job)=>job.delay), streams:transport.state().activeStreams, polling:transport.state().fallbackPolling}));
        """)
        self.assertEqual(len(rendered["attempts"]), 1)
        self.assertEqual(rendered["applied"], [["fresh", 2]])
        self.assertIn(5000, rendered["delays"])
        self.assertEqual(rendered["streams"], 1)
        self.assertFalse(rendered["polling"])

    def test_transport_rejects_poll_after_json_decode_and_closed_stream_callbacks(self) -> None:
        rendered = run_app_script("""
          const {createTransport} = await import(process.env.APP_URL);
          const jobs=[]; let serial=0; const applied=[]; const streams=[]; let resolveJson;
          const timers={setTimeout(fn,delay){const job={id:++serial,fn,delay,cleared:false};jobs.push(job);return job.id},clearTimeout(id){const job=jobs.find((x)=>x.id===id);if(job)job.cleared=true}};
          class Source { constructor(url){this.url=url;this.listeners={};streams.push(this)} addEventListener(name,fn){this.listeners[name]=fn} close(){this.closed=true} }
          const fetchImpl=()=>Promise.resolve({ok:true,json:()=>new Promise((resolve)=>{resolveJson=resolve})});
          const transport=createTransport({EventSourceImpl:Source,fetchImpl,timers,onBundle:(bundle,meta)=>applied.push([bundle.revision,meta.source]),onConnection:()=>{},onElapsed:()=>{}});
          transport.open('session=a',1); streams[0].listeners.error(); jobs.find((job)=>job.delay===5000).fn(); await Promise.resolve();
          transport.open('session=b',2); resolveJson({revision:'old'}); await Promise.resolve(); await Promise.resolve();
          streams[0].listeners.snapshot({data:JSON.stringify({revision:'late'})}); streams[0].listeners.error();
          console.log(JSON.stringify({applied,state:transport.state(),streams:streams.length}));
        """)
        self.assertEqual(rendered["applied"], [])
        self.assertEqual(rendered["state"]["generation"], 2)
        self.assertEqual(rendered["state"]["activeStreams"], 1)

    def test_selection_failure_catalog_refresh_and_rollback_window(self) -> None:
        rendered = run_app_script("""
          const {createSelectionController} = await import(process.env.APP_URL);
          const resolvers=[]; const sync=[]; const applied=[]; const errors=[]; const openings=[];
          const fetchImpl=()=>new Promise((resolve)=>resolvers.push(resolve)); const transport={open:(query,generation)=>openings.push([query,generation]),close:()=>{}};
          const controller=createSelectionController({fetchImpl,transport,sync:(query)=>sync.push(query),apply:(bundle)=>applied.push(bundle.revision),onError:(message)=>errors.push(message)});
          controller.seed('session=a',{revision:'A',catalog:[],projects:[]});
          const bad=controller.select('session=b'); resolvers[0]({ok:true,json:async()=>{throw new Error('bad json')}}); await bad;
          const good=controller.select('session=b'); resolvers[1]({ok:true,json:async()=>({revision:'B',catalog:[{session_id:'b'}],projects:[]})}); await good;
          controller.acceptStreamSnapshot(2); controller.initialStreamFailed(); resolvers[2]({ok:false,status:404}); await Promise.resolve(); await Promise.resolve();
          console.log(JSON.stringify({state:controller.state(),sync,applied,errors,openings}));
        """)
        self.assertEqual(rendered["state"]["query"], "session=b")
        self.assertEqual(rendered["state"]["bundle"]["revision"], "B")
        self.assertEqual(rendered["sync"], ["session=a", "session=a", "session=b"])
        self.assertEqual(rendered["errors"], ["Selection unavailable"])

    def test_duration_uses_finished_time_and_mini_graph_changes_with_node_states(self) -> None:
        rendered = run_app_script("""
          const app=await import(process.env.APP_URL);
          const completed={session_id:'done',status:'passed',started_at:'2026-08-01T00:00:00Z',finished_at:'2026-08-06T00:00:00Z',nodes:{a:{id:'a',state:'passed'}}};
          const running={session_id:'run',status:'running',started_at:'2026-08-01T00:00:00Z',nodes:{a:{id:'a',state:'running'},b:{id:'b',state:'waiting'}}};
          console.log(JSON.stringify({long:app.formatDuration('2026-08-01T00:00:00Z',new Date('2026-08-06T00:00:00Z')),completed:app.buildAllViewModel({projects:[{cwd:'/x',running:[],completed:[completed]}]},new Date('2026-08-20T00:00:00Z')).projects[0].completed[0].elapsed,mini:app.sessionMiniModel(running)}));
        """)
        self.assertEqual(rendered["long"], "120:00:00")
        self.assertEqual(rendered["completed"], "120:00:00")
        self.assertEqual(rendered["mini"], {"running": 1, "waiting": 1, "terminal": 0})

    def test_accepted_poll_updates_committed_bundle_and_catalog_before_rollback(self) -> None:
        rendered = run_app_script("""
          const {createSelectionController}=await import(process.env.APP_URL); const applied=[]; const catalogs=[]; const opened=[]; const resolvers=[];
          const fetchImpl=()=>new Promise((resolve)=>resolvers.push(resolve)); const transport={open:(q,g)=>opened.push([q,g]),close:()=>{}}; const controller=createSelectionController({transport,fetchImpl,apply:(b)=>applied.push(b.revision),refreshCatalog:(c)=>catalogs.push(c.map((x)=>x.session_id))});
          controller.seed('session=a',{revision:'A0',catalog:[{session_id:'a'}],projects:[]});
          controller.acceptStreamSnapshot(1,{revision:'A1',catalog:[{session_id:'a'},{session_id:'new'}],projects:[]});
          const select=controller.select('session=b'); resolvers[0]({ok:true,json:async()=>({revision:'B',catalog:[{session_id:'b'}],projects:[]})}); await select;
          controller.initialStreamFailed(2); resolvers[1]({ok:false,status:404}); await Promise.resolve(); await Promise.resolve();
          console.log(JSON.stringify({state:controller.state(),applied,catalogs,opened}));
        """)
        self.assertEqual(rendered["state"]["bundle"]["revision"], "A1")
        self.assertEqual(rendered["catalogs"][-1], ["a", "new"])
        self.assertEqual(rendered["state"]["query"], "session=a")
        self.assertEqual(rendered["opened"], [["session=a", 1], ["session=b", 2], ["session=a", 3]])

    def test_transport_never_overlaps_deferred_polls_and_recovery_clears_fallback(self) -> None:
        rendered = run_app_script("""
          const {createTransport}=await import(process.env.APP_URL); const jobs=[]; let serial=0; const pending=[]; const streams=[];
          const timers={setTimeout(fn,delay){const job={id:++serial,fn,delay,cleared:false};jobs.push(job);return job.id},clearTimeout(id){const job=jobs.find((x)=>x.id===id);if(job)job.cleared=true}};
          let Recovered=null; function MaybeSource(url){if(!Recovered)throw new Error('offline');const source=new Recovered(url);streams.push(source);return source}
          const fetchImpl=()=>new Promise((resolve)=>pending.push(resolve));
          const transport=createTransport({EventSourceImpl:MaybeSource,fetchImpl,timers,onBundle:()=>{},onConnection:()=>{},onElapsed:()=>{}});
          transport.open('session=a',1);
          const retry=jobs.find((job)=>job.delay===5000&&!job.cleared); retry.fn();
          const retryAgain=jobs.filter((job)=>job.delay===5000&&!job.cleared).at(-1); retryAgain.fn();
          const beforeResolve={requests:pending.length,activeTimers:jobs.filter((job)=>job.delay===5000&&!job.cleared).length};
          pending[0]({ok:true,json:async()=>({revision:'poll',projects:[]})}); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
          const afterResolve=jobs.filter((job)=>job.delay===5000&&!job.cleared).length;
          Recovered=class {constructor(url){this.url=url;this.listeners={}} addEventListener(name,fn){this.listeners[name]=fn} close(){this.closed=true}};
          jobs.filter((job)=>job.delay===5000&&!job.cleared).at(-1).fn(); streams[0].listeners.snapshot({data:JSON.stringify({revision:'sse',projects:[]})});
          console.log(JSON.stringify({beforeResolve,afterResolve,state:transport.state(),activeTimers:jobs.filter((job)=>job.delay===5000&&!job.cleared).length}));
        """)
        self.assertEqual(rendered["beforeResolve"]["requests"], 1)
        self.assertLessEqual(rendered["beforeResolve"]["activeTimers"], 1)
        self.assertLessEqual(rendered["afterResolve"], 2)  # one retry plus one next fallback at most
        self.assertFalse(rendered["state"]["fallbackPolling"])
        self.assertFalse(rendered["state"]["retryPending"])
        self.assertEqual(rendered["activeTimers"], 0)

    def test_elapsed_updates_only_structured_duration_nodes_and_back_handler_replaces(self) -> None:
        rendered = run_app_script("""
          const app=await import(process.env.APP_URL);
          const card={dataset:{elapsed:'true',prefix:'7s ago',startedAt:'2026-08-14T00:00:00Z'},textContent:'7s ago · 00:00:07'};
          const graphLine={dataset:{elapsed:'node',startedAt:'2026-08-14T00:00:00Z'},textContent:'running · 00:00:07'};
          const terminal={dataset:{},textContent:'passed · 120:00:00'}; const detail={textContent:'selected task remains'};
          const root={querySelectorAll:(selector)=>selector==='[data-elapsed="true"]'?[card]:selector==='[data-elapsed="node"]'?[graphLine]:[]};
          app.updateElapsed(root,new Date('2026-08-14T00:00:09Z')); const identity={card:card===card,line:graphLine===graphLine,detail:detail.textContent};
          class Element {constructor(){this.children=[];this.dataset={};this.classList={add(){},remove(){}};this.hidden=false;this.focusCount=0} append(...items){this.children.push(...items)} replaceChildren(...items){this.children=items} setAttribute(){} addEventListener(){} focus(){this.focusCount++}}
          const ids=new Map(['all-view','focused-view','focus-title','focus-path','node-detail','graph','back-button'].map((id)=>[id,new Element()]));
          globalThis.document={getElementById:(id)=>ids.get(id),createElement:()=>new Element(),createElementNS:()=>new Element()};
          const snapshot={session_id:'a',title:'A',nodes:{},edges:[]}; let first=0;let second=0;
          app.renderFocused(snapshot,()=>first++); app.renderFocused(snapshot,()=>second++); ids.get('back-button').onclick();
          console.log(JSON.stringify({card:card.textContent,graph:graphLine.textContent,terminal:terminal.textContent,identity,first,second,backFocus:ids.get('back-button').focusCount}));
        """)
        self.assertEqual(rendered["card"], "7s ago · 00:00:09")
        self.assertEqual(rendered["graph"], "running · 00:00:09")
        self.assertEqual(rendered["terminal"], "passed · 120:00:00")
        self.assertEqual(rendered["identity"]["detail"], "selected task remains")
        self.assertTrue(rendered["identity"]["card"])
        self.assertTrue(rendered["identity"]["line"])
        self.assertEqual(rendered["first"], 0)
        self.assertEqual(rendered["second"], 1)
        self.assertEqual(rendered["backFocus"], 2)

    def test_staged_selection_preserves_active_then_rolls_back_only_on_confirmed_404(self) -> None:
        rendered = run_app_script("""
          const {createSelectionController} = await import(process.env.APP_URL);
          const requests=[]; const resolvers=[]; const openings=[]; const events=[];
          const fetchImpl=(url, options={}) => new Promise((resolve) => { requests.push(url); resolvers.push(resolve); });
          const transport={open:(query, generation)=>openings.push([query,generation]), close:()=>events.push('close')};
          const controller=createSelectionController({fetchImpl, transport, apply:(bundle)=>events.push(['apply',bundle.revision]), sync:(query)=>events.push(['sync',query])});
          controller.seed('session=a', {revision:'A', catalog:[{session_id:'a'},{session_id:'b'},{session_id:'c'}], projects:[]});
          const b=controller.select('session=b');
          resolvers[0]({ok:false, status:404}); await b;
          const bLate=controller.select('session=b'); const c=controller.select('session=c');
          resolvers[2]({ok:true, json:async()=>({revision:'C', catalog:[], projects:[]})}); await c;
          resolvers[1]({ok:true, json:async()=>({revision:'B', catalog:[], projects:[]})}); await bLate;
          controller.initialStreamFailed();
          resolvers[3]({ok:false,status:404}); await Promise.resolve(); await Promise.resolve();
          console.log(JSON.stringify({state:controller.state(), openings, events, requests}));
        """)
        self.assertEqual(rendered["state"]["query"], "session=a")
        self.assertEqual(rendered["state"]["bundle"]["revision"], "A")
        self.assertEqual(rendered["openings"], [["session=a", 1], ["session=c", 2], ["session=a", 3]])
        self.assertIn("/api/snapshot?session=b", rendered["requests"])
        self.assertIn("/api/snapshot?session=c", rendered["requests"])

    def test_project_grid_selector_and_focused_graph_are_accessible_and_keep_full_detail(self) -> None:
        rendered = run_app_script("""
          const app = await import(process.env.APP_URL);
          class Element {
            constructor(tag='div') { this.tagName=tag; this.children=[]; this.attributes={}; this.dataset={}; this.style={}; this.listeners={}; this.focusCount=0; this.classList={values:new Set(), add:(...v)=>v.forEach((x)=>this.classList.values.add(x)), remove:(...v)=>v.forEach((x)=>this.classList.values.delete(x)), toggle:(v,on)=>on ? this.classList.values.add(v) : this.classList.values.delete(v)}; this.textContent=''; this.hidden=false; }
            append(...items) { this.children.push(...items); } replaceChildren(...items) { this.children=items; } setAttribute(key,value) { this.attributes[key]=String(value); } addEventListener(name, callback) { this.listeners[name]=callback; } focus() { this.focusCount += 1; }
          }
          const ids=new Map(['all-view','empty-state','focused-view','focus-title','focus-path','node-detail','graph','back-button','session-selector'].map((id)=>[id,new Element()]));
          globalThis.document={getElementById:(id)=>ids.get(id), createElement:(tag)=>new Element(tag), createElementNS:(_ns,tag)=>new Element(tag)};
          const node={id:'task:full',kind:'task',label:'Complete safe subject without clipping',description:'Complete safe description without clipping',state:'running',sequence:1,model:'model-x',effort:'high',started_at:'2026-08-14T10:00:00Z'};
          const bundle={projects:[{cwd:'/one',running:[{session_id:'a',title:'Running A',status:'running',nodes:{'task:full':node},edges:[]}],completed:[{session_id:'done',title:'Completed A',status:'passed',nodes:{},edges:[]}]},{cwd:'/two',running:[{session_id:'b',title:'Running B',status:'running',nodes:{},edges:[]}],completed:[]}]};
          app.populateSelector([{session_id:'a',title:'Running A',cwd:'/one'},{session_id:'b',title:'Running B',cwd:'/two'}],'selection=all');
          app.populateSelector([{session_id:'b',title:'Running B',cwd:'/two'}],'session=a'); const retainedSelector=ids.get('session-selector').children.map((entry)=>entry.textContent); const retainedValue=ids.get('session-selector').value;
          app.populateSelector([{session_id:'a',title:'Running A',cwd:'/one'},{session_id:'b',title:'Running B',cwd:'/two'}],'selection=all');
          app.renderAll(bundle,()=>{}); const firstProject=ids.get('all-view').children[0]; const runningCard=firstProject.children[1].children[0]; const completed=firstProject.children[2]; const completedTiming=completed.children[1].children[0].children[2];
          app.renderFocused(bundle.projects[0].running[0],()=>app.renderAll(bundle,()=>{})); const graph=ids.get('graph'); const group=graph.children.find((child)=>child.attributes.class === 'node node-running'); group.listeners.click();
          const detail=ids.get('node-detail').children.map((entry)=>entry.textContent); ids.get('back-button').onclick();
          console.log(JSON.stringify({projectCount:ids.get('all-view').children.length, cardTag:runningCard.tagName, completedTag:completed.tagName, completedOpen:completed.open === true, completedRepaints:completedTiming.dataset.elapsed === 'true', selector:ids.get('session-selector').children.map((entry)=>entry.textContent), retainedSelector, retainedValue, nodeRect:group.children[1].attributes, transform:group.attributes.transform, detail, title:group.children[0].textContent, focusCount:ids.get('back-button').focusCount, allVisible:!ids.get('all-view').hidden, focusedHidden:ids.get('focused-view').hidden}));
        """)
        self.assertEqual(rendered["projectCount"], 2)
        self.assertEqual(rendered["cardTag"], "button")
        self.assertEqual(rendered["completedTag"], "details")
        self.assertFalse(rendered["completedOpen"])
        self.assertFalse(rendered["completedRepaints"])
        self.assertEqual(rendered["selector"], ["All sessions", "Running A — /one", "Running B — /two"])
        self.assertEqual(rendered["retainedSelector"], ["All sessions", "Running B — /two", "a — active session"])
        self.assertEqual(rendered["retainedValue"], "session=a")
        self.assertEqual(rendered["nodeRect"]["width"], "180")
        self.assertEqual(rendered["nodeRect"]["height"], "62")
        self.assertEqual(rendered["transform"], "translate(30 30)")
        self.assertEqual(rendered["title"], "Complete safe subject without clipping")
        self.assertEqual(rendered["detail"], ["Complete safe subject without clipping", "Complete safe description without clipping"])
        self.assertEqual(rendered["focusCount"], 1)
        self.assertTrue(rendered["allVisible"])
        self.assertTrue(rendered["focusedHidden"])


if __name__ == "__main__":
    unittest.main()
