// DOM-level regression tests: the production HTML and app.js, no browser/downloads.
const {JSDOM}=require(process.env.JSDOM_PATH || '/tmp/pocket-sync-ui-test/node_modules/jsdom');
const fs=require('node:fs');const assert=require('node:assert/strict');
(async()=>{
 const live=await (await fetch('http://127.0.0.1:8891/api/state')).json();
 live.naming={enabled:false,digits:3};
 live.phase='ready';live.scan_id='fixture-scan';live.extras=[];
 live.tracks=Array.from({length:9},(_,i)=>({id:String(i).padStart(22,'0'),name:`Example song ${i+1}`,artists:['Example Artist'],album:'Example album',duration:115,cover:null,url:'https://open.spotify.com/track/'+String(i).padStart(22,'0'),position:i+1,status:'missing',file:null,reason:'Not found',error:'No automatic match',error_code:'no_match',help:'Choose a recording.'}));
 const dom=new JSDOM(fs.readFileSync('playlist_sync/web/index.html','utf8'),{url:'http://127.0.0.1:8891/',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window;const doc=w.document;const $=id=>doc.getElementById(id);let calls=[],namingRequests=[];
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
 w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
 w.HTMLElement.prototype.scrollIntoView=function(){};w.setInterval=()=>0;w.scrollTo=()=>{};w.requestAnimationFrame=()=>0;
 w.localStorage.setItem('pocket-sync-walkthrough-v1','seen');
 w.fetch=async(path,opts)=>{
  if(path==='/api/state')return {ok:true,json:async()=>structuredClone(live)};
  if(path==='/api/history')return {ok:true,json:async()=>({runs:[]})};
  if(path==='/api/recordings/search')return {ok:true,json:async()=>({videos:[{id:'jNQXAC9IVRw',url:'https://www.youtube.com/watch?v=jNQXAC9IVRw',title:'Preview',channel:'Test',duration:115,thumbnail:'https://i.ytimg.com/vi/jNQXAC9IVRw/hqdefault.jpg'}]})};
  if(path==='/api/order/preview'){const data=JSON.parse(opts.body);namingRequests.push(data);return {ok:true,json:async()=>({id:'order-test',folder:live.settings.folder,changes:[],enabled:data.enabled,digits:data.digits})};}
  if(path==='/api/order/apply'){const selected=namingRequests.at(-1);live.naming={enabled:selected.enabled,digits:selected.digits};return {ok:true,json:async()=>({renamed:0,...live.naming})};}
  if(path==='/api/sync'){calls.push(JSON.parse(opts.body));return {ok:true,json:async()=>({ok:true})};}
  return {ok:true,json:async()=>({runs:[]})};
 };
 w.eval(fs.readFileSync('playlist_sync/web/app.js','utf8')+'\nwindow.__testRefresh=refresh;');
 const tick=()=>new Promise(r=>setTimeout(r,10));await tick();
 $('match-remaining').click();await tick();assert.match($('match-progress').textContent,/Song 1 of 9/);
 // Preview neither selects a source nor starts a download.
 doc.querySelector('[data-preview]').click();assert.equal(doc.querySelectorAll('#recording-preview iframe').length,1);assert.equal($('source-url').value,'');assert.equal(calls.length,0);
 doc.querySelector('[data-recording]').click();$('source-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();
 assert.match($('match-progress').textContent,/Song 2 of 9/);assert.equal(doc.querySelectorAll('iframe').length,0);assert.equal(calls.length,0);
 $('match-back').click();await tick();assert.equal($('source-url').value,'https://www.youtube.com/watch?v=jNQXAC9IVRw');
 $('source-close').click();$('match-remaining').click();await tick();assert.equal($('source-url').value,'https://www.youtube.com/watch?v=jNQXAC9IVRw');
 // All nine choices can be saved without any network sync request.
 for(let i=0;i<9;i++){
  $('source-url').value='https://www.youtube.com/watch?v=jNQXAC9IVRw';$('source-url').dispatchEvent(new w.Event('input'));
  $('source-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();
 }
 assert.match($('match-progress').textContent,/9 matched/);assert.equal(calls.length,0);
 $('match-download').click();await tick();assert.equal(calls.length,1);assert.equal(calls[0].ids.length,9);assert.equal(Object.keys(calls[0].sources).length,9);assert.equal($('source-dialog').open,false);
 // Skip never silently submits; stale comparisons cannot download saved choices.
 $('match-remaining').click();await tick();$('match-skip').click();await tick();assert.match($('match-progress').textContent,/Song 2 of 9/);
 $('match-finish').click();assert.match($('match-progress').textContent,/8 matched/);
 live.scan_id='changed';await w.__testRefresh();$('match-download').click();await tick();assert.equal(calls.length,1);assert.match($('source-feedback').textContent,/comparison changed/);
 // Naming is off by default; controls are visible only after explicit opt-in.
 $('source-dialog').close();$('help-settings').click();
 assert.equal($('naming-enabled').checked,false);assert.equal($('naming-options').hidden,true);
 $('naming-enabled').checked=true;$('naming-enabled').dispatchEvent(new w.Event('change'));
 $('naming-digits').value='4';$('naming-digits').dispatchEvent(new w.Event('change'));
 assert.equal($('naming-options').hidden,false);assert.match($('naming-example').textContent,/0001/);
 $('naming-review').click();await tick();assert.equal(namingRequests.at(-1).enabled,true);assert.equal(namingRequests.at(-1).digits,4);
 assert.equal(live.naming.enabled,false); // Preview must not change the preference.
 $('order-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();assert.equal(live.naming.enabled,true);
 $('order-dialog').close();$('help-settings').click();assert.equal($('naming-digits').value,'4');
 $('naming-enabled').checked=false;$('naming-enabled').dispatchEvent(new w.Event('change'));$('naming-review').click();await tick();
 $('order-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();assert.equal(live.naming.enabled,false);
 dom.window.close();console.log('PASS matching queue, preview cleanup, batch/stale guards, default-off numbering, padding, opt-in and disable');
})().catch(e=>{console.error(e);process.exit(1)});
