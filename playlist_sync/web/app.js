'use strict';
const $ = id => document.getElementById(id);
let state, token, tab = 'missing', listSignature = '', requesting = false;
// Selection belongs to this comparison, library, and destination only.
let selectedTracks=new Set(),selectionKey='';
const recoveryGuideKey = 'pocket-sync-recording-guide-v2';
let recoveryGuideSeen = false;
let lastGuidedTrack = null;
let recoveryGuideTrack = null;
try { recoveryGuideSeen = localStorage.getItem(recoveryGuideKey) === 'seen'; } catch {}

function completeRecoveryGuide() {
  recoveryGuideSeen = true;
  recoveryGuideTrack = null;
  try { localStorage.setItem(recoveryGuideKey, 'seen'); } catch {}
  showTracks();
}
function updateSelection(next){
  const key=JSON.stringify([next.library_id,next.settings.folder,next.scan_id]);
  const available=new Set(next.tracks.filter(x=>x.status==='missing').map(x=>x.id));
  if(key!==selectionKey){
    selectionKey=key;
    try{
      const saved=JSON.parse(sessionStorage.getItem('pocket-selection:'+key));
      selectedTracks=new Set(Array.isArray(saved)?saved:available);
    }catch{selectedTracks=new Set(available);}
  }
  selectedTracks=new Set([...selectedTracks].filter(id=>available.has(id)));
}
function saveSelection(){
  try{sessionStorage.setItem('pocket-selection:'+selectionKey,JSON.stringify([...selectedTracks]));}catch{}
}
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const duration = seconds => `${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
const jobBusy = () => state && ['checking','syncing'].includes(state.phase);
let timedJob = null, waitStarted = 0;
function loadingLogo() {
  return $('loading-logo').content.cloneNode(true);
}
function showWait(id, active, message) {
  const status = $(id);
  status.classList.toggle('is-waiting', active);
  if (message !== undefined && status.textContent !== message) {
    if (status.lastChild?.nodeType === Node.TEXT_NODE) status.lastChild.data = message;
    else status.append(message);
  }
  const logo = status.querySelector('.orbit-logo');
  if (active && !logo) status.prepend(loadingLogo());
  if (!active) logo?.remove();
}
const busy = () => jobBusy() || (state && state.choosing_folder) || pickerPending;
const settingsChanged = () => state && ($('playlist').value.trim()!==state.settings.playlist || $('folder').value.trim()!==state.settings.folder);
const rowsFor = status => state.tracks.filter(x => x.status === status);
function notice(text) { $('notice').textContent=text; $('notice').hidden=!text; }
async function post(path, body) {
  if(requesting) return false;
  requesting=true;
  try {
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({library_id:state?.library_id,...body})});
    const result=await response.json();
    if(!response.ok) throw new Error(result.error || 'The request could not be completed.');
    notice('');
    await refresh();
    return true;
  } catch(error) {notice(error.message); return false;} finally {requesting=false;}
}
function empty(title, message, symbol='♫') {
  return `<div class="empty"><span class="empty-icon" aria-hidden="true">${symbol}</span><h3>${escape(title)}</h3><p>${escape(message)}</p></div>`;
}
function showTracks() {
  if(!state) return;
  $('match-remaining').disabled=busy()||!state.scan_id||settingsChanged()||!state.tracks.some(x=>x.status!=='present'&&['no_match','verification'].includes(x.error_code));
  const query=$('search').value.toLowerCase().trim();
  const signature=JSON.stringify([state.tracks,state.extras,state.phase,state.current_id,tab,query,settingsChanged(),[...selectedTracks],recoveryGuideSeen,recoveryGuideTrack,currentView]);
  if(signature===listSignature)return;
  listSignature=signature;
  requestRecordingSpotlight();
  if(!state.scan_id && !state.tracks.length) {
    $('track-list').innerHTML=state.phase==='checking' ? '' : $('empty-template').innerHTML;
    return;
  }
  if(tab==='extras') {
    const files=state.extras.filter(x => `${x.name} ${x.artist} ${x.file}`.toLowerCase().includes(query));
    $('track-list').innerHTML='<div class="other-intro">These files aren’t matched to this playlist. They stay in your folder and are never removed by a sync.</div>'+ (files.length ? files.map(x=>`<div class="other-file"><span class="file-icon" aria-hidden="true">♫</span><div>${escape(x.name)}<small>${escape(x.artist)}${x.artist?' · ':''}${escape(x.file)}</small>${x.import_id?'<small>Imported via Custom audio</small>':''}${x.error?`<small>${escape(x.error)}</small>`:''}</div></div>`).join('') : empty('Everything accounted for.','No other files found in this folder.','✓'));
    return;
  }
  const rows=rowsFor(tab).filter(x=>`${x.name} ${x.artists.join(' ')} ${x.album}`.toLowerCase().includes(query));
  const guidedTrack = !recoveryGuideSeen && currentView === 'library' && tab === 'missing' &&
    state.scan_id && !busy() && !settingsChanged()
    ? rows.find(row => row.error_code === 'no_match')
    : null;
  $('list-caption').textContent=`${rows.length} song${rows.length===1?'':'s'}`;
  if(!rows.length) {
    $('track-list').innerHTML=query ? empty('No songs found.','Try another title or artist.') : tab==='missing' ? empty(state.phase==='syncing'?'Your songs are arriving.':rowsFor('review').length?'A few matches need your review.':'You’re up to date.',rowsFor('review').length?'There are possible matches in Review. Confirm them or download a separate copy.':'Every playlist track is already in your folder. Add songs on Spotify, then check again.','✓') : tab==='review' ? empty('No uncertain matches.','The songs found in your folder matched by track ID or by title, artist, and duration.','✓') : empty('Your library starts here.','Songs already in your folder will appear here.');
    return;
  }
  $('track-list').innerHTML='<div class="track-header"><span>#</span><span>SONG</span><span class="album">ALBUM</span><span class="duration">TIME</span><span>STATUS</span></div>'+rows.map(row=>{
    const active=state.current_id===row.id && state.phase==='syncing';
    const disabled=busy()||settingsChanged()?'disabled':'';
    const cover=row.cover&&/^https:\/\/(?:i|mosaic)\.scdn\.co\//.test(row.cover) ? `<img class="cover" alt="" loading="lazy" src="${escape(row.cover)}">` : '<span class="cover cover-fallback" aria-hidden="true">♫</span>';
    const label=active?'Downloading…':row.status==='present'?(row.reason==='Confirmed combined recording'?'✓ Combined file':'✓ In folder'):row.status==='review'?'Check match':row.error?'Retry needed':'+ To add';
    const cls=active?'downloading':row.status;
    const statusControl=row.status==='missing'&&!active?`<button class="badge missing add-track" data-download="${row.id}" aria-label="${row.reuse_file?'Copy song':'Add song'}: ${escape(row.name)}" ${disabled}>${row.reuse_file?'Copy song':row.error?'Retry':'Add song'} ↓</button>`:`<span class="badge ${cls}" title="${escape(row.reason)}">${label}</span>`;
    const guide = row === guidedTrack;
    const highlight = guide && recoveryGuideTrack === row.id;
    const recordingButton = `<button class="button secondary${highlight?' recording-guide-target':''}" data-source="${row.id}" ${guide?'aria-describedby="recovery-instructions"':''} ${disabled}>Choose recording…</button>`;
    const recoveryHint = guide ? '<aside class="recovery-hint" aria-label="Recording help"><strong>Try a manual match</strong><p id="recovery-instructions" role="status">Pocket Sync couldn’t find a recording for this song. ' + (highlight ? 'Click the highlighted Choose recording… button to continue.' : 'You can search YouTube or paste a video link to choose the recording yourself.') + '</p><div class="recovery-actions"><button type="button" class="button primary" data-show-recovery>Show me how</button><button type="button" class="button secondary" data-dismiss-recovery>Dismiss tip</button></div></aside>' : '';
    const candidates=row.status==='review'?`<div class="review-box">${row.candidates.map(c=>`<div class="candidate"><div>${escape(c.title)}<small>${escape(c.artist || 'Artist tag unavailable')} · ${duration(c.duration)}${c.error?' · '+escape(c.error):''}</small><small>${escape(c.file)}</small></div><button class="button secondary" data-match="${row.id}" data-file="${escape(c.file)}" ${disabled} ${c.error?'disabled':''}>Use this file</button></div>`).join('')}<button class="button secondary" data-download="${row.id}" ${disabled}>Download a separate copy ↓</button></div>`:'';
    return `<article class="track"><span class="track-number">${row.status==='missing'?`<label class="track-pick"><input type="checkbox" data-select="${row.id}" aria-label="Include ${escape(row.name)} in this sync" ${selectedTracks.has(row.id)?'checked':''} ${disabled}></label>`:row.position}</span><div class="song-main">${cover}<div class="song-text"><a href="${escape(row.url)}" target="_blank" rel="noreferrer">${escape(row.name)}</a><small>${escape(row.artists.join(', '))}</small></div></div><span class="album" title="${escape(row.album)}">${escape(row.album)}</span><span class="duration">${duration(row.duration)}</span>${statusControl}${row.error?`<div class="track-error">Last attempt: ${escape(row.error)}</div><div class="match-help"><span>${escape(row.help||'')}</span>${recordingButton}</div>`:''}${row.reuse_file?`<div class="match-help">Ready to copy from your Mac: ${escape(row.reuse_file)}</div>`:''}${row.status==='missing'&&!row.error?`<div class="match-help">${recordingButton}</div>`:''}${candidates}${recoveryHint}</article>`;
  }).join('');
  if (guidedTrack && lastGuidedTrack !== guidedTrack.id && !document.querySelector('dialog[open]')) {
    lastGuidedTrack = guidedTrack.id;
    $('recovery-instructions')?.scrollIntoView({block: 'nearest'});
  }
}
function render(next) {
  const first=!state,changedLibrary=first||state.library_id!==next.library_id;
  const changedSettings=changedLibrary||state.library?.updated_at!==next.library?.updated_at;
  const recovered=state?.phase==='error'&&next.phase!=='error';
  updateSelection(next);
  state=next;token=next.token;
  if(recovered)notice('');
  if(changedSettings){
    $('playlist').value=state.settings.playlist;$('folder').value=state.settings.folder;
    $('folder').readOnly=true;$('folder-manual').textContent='Enter path manually';
  }
  if(changedLibrary){
    recoveryGuideTrack = null;
    expandedLibraries.add(state.library_id);sidebarSignature='';
    $('search').value='';tab='missing';listSignature='';
    document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab==='missing'));
    historyRevision=null;historyRuns=[];historySignature='';historyNewest=null;lastSyncSignature='';
    notice('');
  }
  updateViewContext();
  $('workspace-name').textContent=state.library?.name||'Your music';

  $('folder').title=state.settings.folder;
  $('edit-library').disabled=busy();$('help-library').disabled=busy();$('choose-folder').disabled=busy();$('folder-manual').disabled=busy();
  renderSidebar();
  const edited=settingsChanged();
  $('check').disabled=busy();$('playlist').disabled=busy();$('folder').disabled=busy();
  $('check').innerHTML=state.phase==='checking'?'Checking…':'Check for new songs <span aria-hidden="true">↻</span>';
  const working = jobBusy();
  document.body.classList.toggle('is-working', working);
  $('library-section').classList.toggle('is-checking',state.phase==='checking');
  showWait('status',working,state.message);
  $('status-dot').hidden=working;
  $('history-job-status').hidden=!working;
  showWait('history-job-status',working,state.message);
  $('history-stop').hidden=!working;
  $('status-dot').className='status-dot '+(busy()?'busy':state.phase==='error'?'error':state.scan_id?'ready':'');
  $('folder-note').textContent=edited?'Check again after changing the folder':state.folder_available?'Folder available':state.settings.folder?'Folder unavailable · Connect your player or choose a folder':'Choose a destination for this library';
  $('folder-note').style.color=state.folder_available?'':'#ac6045';
  const reusable=rowsFor('missing').filter(x=>x.reuse_file).length;
  const missing=rowsFor('missing').length,present=rowsFor('present').length,review=rowsFor('review').length;
  $('summary').hidden=!state.scan_id;
  $('count-total').textContent=state.tracks.length;$('count-missing').textContent=missing;$('count-present').textContent=present;$('count-review').textContent=review;
  for(const [name,count] of [['missing',missing],['present',present],['review',review],['extras',state.extras.length]]) $('tab-'+name).textContent=count;
  $('sync').disabled=busy()||!state.scan_id||!selectedTracks.size||edited||!state.folder_available;
  $('sync').innerHTML=!state.scan_id?'Check the playlist first':missing?`Sync ${selectedTracks.size} selected song${selectedTracks.size===1?'':'s'} <span aria-hidden="true">↓</span>`:'All songs accounted for <span aria-hidden="true">✓</span>';
  $('bulk-selection').hidden=tab!=='missing'||!state.scan_id||!missing;
  $('selection-count').textContent=`${selectedTracks.size} of ${missing} selected${missing-selectedTracks.size?' · '+(missing-selectedTracks.size)+' left out this round':''}`;
  $('select-all').disabled=busy()||edited||selectedTracks.size===missing;
  $('select-none').disabled=busy()||edited||!selectedTracks.size;
  $('playback-order').disabled=busy()||!state.settings.folder||!state.folder_available;
  $('playback-order').hidden=!state.naming?.enabled;
  $('naming-note').hidden=!state.naming?.enabled;
  $('combine-playlist').disabled=busy()||!state.scan_id||edited||!state.folder_available;
  $('sync').hidden=busy();$('stop').hidden=!jobBusy();
  $('job-progress').hidden=!working;
  const progress = state.progress;
  $('progress').max = Math.max(1, progress.total);
  if (progress.total) $('progress').value = progress.done;
  else $('progress').removeAttribute('value');
  let progressText = '';
  if (progress.total && state.phase === 'checking') {
    progressText = `${progress.done} of ${progress.total} playlist entries read`;
  } else if (progress.total && state.phase === 'syncing') {
    progressText = `${progress.done} of ${progress.total} processed · ${progress.added || 0} added${progress.failed ? ' · ' + progress.failed + ' failed' : ''}`;
  }
  if ($('progress-text').textContent !== progressText) $('progress-text').textContent = progressText;
  if (timedJob !== state.job_id) {
    timedJob = state.job_id;
    waitStarted = Date.now();
  }
  $('wait-note').hidden = !working || Date.now() - waitStarted < 12000;
  $('library-title').textContent=state.playlist_name||state.library?.name||'Your playlist';
  $('playlist-name').textContent=state.playlist_name||'The playlist you want to keep up with';
  $('checked').textContent=state.checked_at?`Last checked ${new Date(state.checked_at).toLocaleString([], {dateStyle:'medium',timeStyle:'short'})} · ${state.local_count} local file${state.local_count===1?'':'s'}${reusable?' · '+reusable+' ready to copy locally':''}${state.skipped.length?' · '+state.skipped.length+' unavailable entries skipped':''}`:'Check your playlist to see what’s ready to add.';
  $('spotify-link').hidden=!state.settings.playlist;
  $('spotify-link').href=state.settings.playlist;
  $('error-list').textContent=[...state.errors,...state.skipped.map(x=>`${x.name}: ${x.reason}`)].join('\n');
  $('log').textContent=state.log.length?state.log.join('\n'):'No activity yet.';
  if(state.phase==='error')notice(state.message);
  renderCustom();
  showTracks();
  updateHistorySummary();
  if(currentView==='history')renderHistory();
  if(first)offerWalkthrough();
}
async function refresh(){
  try{
    const response=await fetch('/api/state');
    if(!response.ok)throw new Error('Could not reach the local app.');
    render(await response.json());
    $('status').removeAttribute('title');
  }catch(error){
    document.body.classList.remove('is-working');
    showWait('status',false,'Lost the connection to Pocket Sync. Reopen the app or check its Terminal window.');
    $('status-dot').hidden=false;
    $('job-progress').hidden=true;
    $('sync').disabled=true;
    $('check').disabled=true;
  }
}
$('check').addEventListener('click',()=>{post('/api/check',{playlist:$('playlist').value.trim(),folder:$('folder').value.trim()});});
$('sync').addEventListener('click',()=>{if(selectedTracks.size)post('/api/sync',{scan_id:state.scan_id,ids:[...selectedTracks]});});
$('stop').addEventListener('click',()=>post('/api/stop',{}));
$('search').addEventListener('input',showTracks);
for(const input of [$('playlist'),$('folder')]) input.addEventListener('input',()=>{if(state)render(state);});
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{
  tab=button.dataset.tab;
  document.querySelectorAll('[data-tab]').forEach(x=>{x.classList.toggle('active',x===button);x.setAttribute('aria-current',x===button?'page':'false');});
  render(state);
}));
$('select-all').addEventListener('click',()=>{
  selectedTracks=new Set(rowsFor('missing').map(x=>x.id));saveSelection();render(state);
});
$('select-none').addEventListener('click',()=>{
  selectedTracks.clear();saveSelection();render(state);
});
$('track-list').addEventListener('click', event => {
  const action = event.target.closest('[data-show-recovery], [data-dismiss-recovery]');
  if (!action) return;
  const id = action.closest('.track').querySelector('[data-source]').dataset.source;
  if (action.hasAttribute('data-show-recovery')) {
    recoveryGuideTrack = id;
    showTracks();
  } else {
    completeRecoveryGuide();
  }
  const button = $('track-list').querySelector(`[data-source="${CSS.escape(id)}"]`);
  button?.focus({preventScroll:true});
  if (action.hasAttribute('data-show-recovery')) button?.scrollIntoView({block:'center'});
});
$('track-list').addEventListener('change',event=>{
  const input=event.target.closest('[data-select]');
  if(!input||busy()||settingsChanged())return;
  if(input.checked)selectedTracks.add(input.dataset.select);else selectedTracks.delete(input.dataset.select);
  const id=input.dataset.select;
  saveSelection();render(state);
  document.querySelectorAll('[data-select]').forEach(x=>{if(x.dataset.select===id)x.focus();});
});
$('track-list').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.source)chooseSource(button.dataset.source);
  if(button.dataset.match)post('/api/match',{id:button.dataset.match,file:button.dataset.file});
  if(button.dataset.download)post('/api/sync',{scan_id:state.scan_id,ids:[button.dataset.download]});
});
const statusNames={running:'Syncing',completed:'Completed',issues:'Finished with issues',failed:'Failed',stopped:'Stopped',interrupted:'Interrupted',added:'Added & verified',already_present:'Already present',queued:'Waiting',downloading:'Downloading',not_attempted:'Not attempted',unknown:'Not recorded',covered:'Covered by combined file'};
let historyScope=null;
let currentView='library',historyRuns=[],historyRevision=null,historyLoading=false,historySignature='',sourceTrack=null,lastSyncSignature='',historyNewest=null;
const logCache=new Map();
const formatTime=value=>value?new Date(value).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}):'Start time not recorded';
function updateViewContext(){
  if(!state)return;
  const custom=currentView==='custom'||(currentView==='history'&&historyScope==='custom');
  const name=custom?'Custom audio':state.library?.name||'Your music';
  document.title=name+' · Pocket Sync';$('breadcrumb-library').textContent=name;
  $('custom-view').classList.toggle('side-active',custom);
}
function setView(view){
  currentView=view;updateViewContext();
  window.scrollTo(0,0);
  for(const id of ['library-intro','setup','library-section','activity'])$(id).hidden=view!=='library';
  $('history-section').hidden=view!=='history';
  $('custom-section').hidden=view!=='custom';
  sidebarSignature='';renderSidebar();
  if(view==='history')loadHistory();
  if(view==='library')showTracks();
}
function updateHistorySummary(){
  const run=state.last_sync;
  $('last-sync').hidden=!run;
  if(run&&JSON.stringify(run)!==lastSyncSignature){
    lastSyncSignature=JSON.stringify(run);
    $('last-sync').className='last-sync '+(run.failed||['failed','issues','stopped','interrupted'].includes(run.status)?'issues':'');
    $('last-sync').innerHTML=`<div><strong>Last sync: ${escape(statusNames[run.status]||run.status)}</strong><small>${run.added||0} added${run.failed?' · '+run.failed+' failed':''} · ${escape(formatTime(run.finished_at||run.started_at))}</small></div><button class="button secondary" data-view-history>View sync history →</button>`;
  }
  if(currentView==='history'&&historyRevision!==state.history_revision)loadHistory();
}
function canRetry(item,run){
  return !busy()&&!settingsChanged()&&state.scan_id&&run.library_id===state.library_id&&run.folder===state.settings.folder&&state.tracks.some(t=>t.id===item.id&&t.status!=='present');
}
function renderHistory(){
  const signature=JSON.stringify([historyRuns,state.scan_id,state.phase,state.settings.folder,state.library_id,settingsChanged()]);
  if(signature===historySignature)return;
  historySignature=signature;
  const opened=new Set([...document.querySelectorAll('.history-run[open]')].map(x=>x.dataset.job));
  $('history-caption').textContent=$('history-all').checked?'Most recent 100 syncs across all libraries':historyScope==='custom'?'Custom audio imports · all destinations':`Syncs for ${state.library?.name||'this library'} · all destinations`;
  if(!historyRuns.length){historyNewest=null;$('history-list').innerHTML=empty('Your sync history starts here.','Each sync is saved here, including added songs, failures, destination filenames, and completion times.','↺');return;}
  if(focusHistoryJob){opened.clear();opened.add(focusHistoryJob);historyNewest=historyRuns[0].id;focusHistoryJob=null;}
  if(historyNewest!==historyRuns[0].id){opened.clear();opened.add(historyRuns[0].id);historyNewest=historyRuns[0].id;}
  $('history-list').innerHTML=historyRuns.map((run,index)=>{
    const counts=run.counts||{};
    const summary=[`${run.added||0} added`,counts.failed?`${counts.failed} failed`:'',counts.downloading?`${counts.downloading} downloading`:'',counts.queued?`${counts.queued} waiting`:'',counts.already_present?`${counts.already_present} already present`:'',counts.covered?`${counts.covered} covered`:'',counts.not_attempted?`${counts.not_attempted} not attempted`:''].filter(Boolean).join(' · ');
    const items=run.items.map(item=>{
      const enabled=canRetry(item,run), row=state.tracks.find(x=>x.id===item.id);
      const failed=['failed','interrupted','stopped','unknown'].includes(item.status);
      const present=run.library_id===state.library_id&&run.folder===state.settings.folder&&row?.status==='present';
      const spotify=/^https:\/\/open\.spotify\.com\/track\/[A-Za-z0-9]{22}$/.test(item.url||'')?`<a href="${escape(item.url)}" target="_blank" rel="noreferrer">Spotify page ↗</a>`:'';
      const youtube=/^https:\/\/www\.youtube\.com\/(?:watch\?v=[A-Za-z0-9_-]{11}|playlist\?list=[A-Za-z0-9_-]{10,100})$/.test(item.source_url||'')?`<a href="${escape(item.source_url)}" target="_blank" rel="noreferrer">YouTube recording ↗</a>`:'';
      const key=run.id+'/'+item.id;
      return `<div class="history-song"><div class="history-song-title">${escape(item.name)}<small>${escape(item.artists.join(', '))}</small></div><span class="history-song-status ${escape(item.status)}">${escape(item.status==='added'&&item.method==='local_copy'?'Copied locally & verified':statusNames[item.status]||item.status)}</span><div class="history-song-detail"><p>${escape(item.message||'')}</p>${item.help?`<p>${escape(item.help)}</p>`:''}${item.source_file?`<p class="history-file">Copied from: ${escape(item.source_file)}</p>`:''}${item.file?`<p class="history-file">Saved to: ${escape(item.file)}</p>`:''}${present?'<p>✓ Found in your latest folder check.</p>':''}${item.finished_at?`<p>${escape(formatTime(item.finished_at))}</p>`:''}</div><div class="history-song-actions">${spotify}${youtube}${failed&&!present&&run.kind!=='custom'?`<button class="button secondary" data-retry="${item.id}" ${enabled?'':'disabled'} title="${enabled?'Retry this track':'Check the playlist and this folder before retrying'}">Retry download</button><button class="button secondary" data-source="${item.id}" ${enabled?'':'disabled'}>Choose recording…</button>`:''}</div><details class="technical" data-log-key="${key}"><summary>Technical download log</summary><pre>${escape(logCache.get(key)||'Open to load the saved download log.')}</pre></details></div>`;
    }).join('');
    return `<details class="history-run" data-job="${run.id}" ${opened.has(run.id)||(!opened.size&&index===0)?'open':''}><summary><span class="run-time">${escape(formatTime(run.started_at||run.finished_at))}</span><span class="run-result"><strong>${escape(summary)}</strong><small>${escape(run.playlist_name||'Playlist sync')} · ${run.total} requested${run.kind==='combined'?' · combined recording':''}</small></span><span class="run-badge ${escape(run.status)}">${escape(statusNames[run.status]||run.status)}</span></summary><div class="run-folder">Destination: ${escape(run.folder)}</div><div class="run-note">${escape(run.message||'')}${run.started_at?`<br>Started ${escape(formatTime(run.started_at))}`:''}${run.finished_at?`<br>Finished ${escape(formatTime(run.finished_at))}`:''}</div>${items||'<div class="run-note">No individual track details were saved for this older sync.</div>'}</details>`;
  }).join('');
  document.querySelectorAll('details.technical').forEach(detail=>detail.addEventListener('toggle',async()=>{
    if(!detail.open)return;
    const key=detail.dataset.logKey;
    try{
      if(!logCache.has(key)){
        const [job,track]=key.split('/');
        const response=await fetch(`/api/history/${job}/log/${track}`);
        const result=await response.json();
        if(!response.ok)throw new Error(result.error);
        logCache.set(key,result.log);
      }
      detail.querySelector('pre').textContent=logCache.get(key);
    }catch(error){detail.querySelector('pre').textContent=error.message;}
  }));
}
async function loadHistory(force=false){
  if(historyLoading||!state)return;
  historyLoading=true;
  const revision=state.history_revision,libraryId=historyScope||state.library_id,allLibraries=$('history-all').checked;
  try{
    const filter=allLibraries?'':'?library='+encodeURIComponent(libraryId);
    const response=await fetch('/api/history'+filter);
    const result=await response.json();
    if(!response.ok)throw new Error(result.error);
    if((historyScope||state.library_id)!==libraryId||$('history-all').checked!==allLibraries)return;
    historyRuns=result.runs;historyRevision=revision;
    if(force)historySignature='';
    renderHistory();
  }catch(error){notice('Could not load sync history: '+error.message);}
  finally{historyLoading=false;}
}
let spotlightFrame = 0;
function requestRecordingSpotlight() {
  if (spotlightFrame) return;
  spotlightFrame = requestAnimationFrame(() => {
    spotlightFrame = 0;
    const overlay = $('recording-spotlight');
    const picker = document.querySelector('#source-dialog[open], #combine-dialog[open]');
    const targets = picker
      ? [...picker.querySelectorAll('.recording-guide-target, [data-recording-context]')]
      : currentView === 'library' && !document.querySelector('dialog[open]')
        ? [...$('track-list').querySelectorAll('.recording-guide-target')]
        : [];
    overlay.toggleAttribute('hidden', !targets.length);
    if (!targets.length) return;

    const host = picker || document.body;
    if (overlay.parentNode !== host) host.append(overlay);
    const caption = picker ? picker.querySelector('.recovery-hint') : targets[0].closest('.track').querySelector('.recovery-hint');
    const bounds = picker ? picker.getBoundingClientRect() : {top: 0, left: 0, right: innerWidth, bottom: innerHeight};
    const openings = [caption, ...targets].map(element => {
      const rect = element.getBoundingClientRect();
      const clip = element.closest('.dialog-scroll')?.getBoundingClientRect() || bounds;
      const left = Math.max(clip.left, rect.left - 6);
      const top = Math.max(clip.top, rect.top - 6);
      const right = Math.min(clip.right, rect.right + 6);
      const bottom = Math.min(clip.bottom, rect.bottom + 6);
      const hole = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      for (const [key, value] of Object.entries({x: left, y: top, width: Math.max(0, right - left), height: Math.max(0, bottom - top), rx: 9})) {
        hole.setAttribute(key, value);
      }
      return hole;
    });
    $('recording-spotlight-openings').replaceChildren(...openings);
  });
}
window.addEventListener('scroll', requestRecordingSpotlight, {capture: true, passive: true});
window.addEventListener('resize', requestRecordingSpotlight);

function showPickerGuide(stage) {
  const guide = $('source-recovery');
  guide.hidden = !stage;
  requestRecordingSpotlight();
  const hasResults = $('recording-results').childElementCount > 0;
  $('recording-query').classList.toggle('recording-guide-target', stage === 'search');
  $('recording-results').classList.toggle('recording-guide-target', stage === 'choose' && hasResults);
  $('source-url').classList.toggle('recording-guide-target', stage === 'choose');
  $('source-url').toggleAttribute('data-recording-context', stage === 'download');
  $('source-download').classList.toggle('recording-guide-target', stage === 'download');
  if (stage === 'search') {
    $('source-recovery-text').textContent = 'Search for the artist and song title. You can edit the search if you need a different version.';
  } else if (stage === 'choose') {
    $('source-recovery-text').textContent = hasResults
      ? 'Compare the artist, version, and duration with Spotify. Select the recording you think matches, or paste a YouTube link.'
      : 'Try a different search, or paste a YouTube link for the recording you want.';
  } else if (stage === 'download') {
    $('source-recovery-text').textContent = 'Check the selected link, then click Download this recording when you’re ready.';
  }
}
function hasRecordingLink(value=$('source-url').value) {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'https:') return false;
    const video = url.hostname === 'youtu.be' ? url.pathname.replace(/^\/+|\/+$/g, '')
      : ['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(url.hostname) && url.pathname === '/watch'
        ? url.searchParams.get('v') : '';
    return /^[A-Za-z0-9_-]{11}$/.test(video || '');
  } catch {
    return false;
  }
}
function chooseSource(id, queued=false){
  if(!queued){matchQueue=null;$('match-queue').hidden=true;}
  recordingSearchNumber++;recordingSearchAbort?.abort();
  stopPreview();
  $('source-scroll').hidden=false;$('source-download').hidden=false;$('match-download').hidden=true;
  $('source-search').hidden=false;$('match-finish').hidden=false;
  $('source-download').textContent=queued?'Save match & next':'Download this recording ↓';
  sourceTrack=state.tracks.find(x=>x.id===id);
  if(!sourceTrack)return;
  const showRecovery = recoveryGuideTrack === id && sourceTrack.error_code === 'no_match';
  $('source-song').textContent=sourceTrack.name+' — '+sourceTrack.artists.join(', ');
  $('source-search').href='https://www.youtube.com/results?search_query='+encodeURIComponent(sourceTrack.artists.join(' ')+' '+sourceTrack.name);
  $('source-url').value='';
  $('source-download').disabled=true;
  $('source-scroll').scrollTop=0;
  $('source-feedback').textContent='';$('source-feedback').style.color='';
  $('recording-query').value=(sourceTrack.artists.join(' ')+' '+sourceTrack.name).slice(0,250);
  $('recording-results').innerHTML='';$('recording-status').textContent='';
  if(!$('source-dialog').open)$('source-dialog').showModal();
  showPickerGuide(showRecovery ? 'search' : null);
  if (!recoveryGuideSeen && sourceTrack.error_code === 'no_match') completeRecoveryGuide();
  searchRecordings();
}
let customPlan=null,customRequest=0,customSignature='';
function renderCustom(){
  $('custom-add').disabled=busy();$('custom-stop').hidden=!jobBusy();
  showWait('custom-job-status',jobBusy(),jobBusy()?state.message:'');
  const folder = $('custom-folder').value.trim();
  $('custom-start').disabled = busy() || !customPlan || !folder ||
    customPlan.input !== $('custom-url').value.trim() || customPlan.library !== state.library_id ||
    ((customPlan.in_destination || customPlan.folder_available === false) && folder === customPlan.folder);$('custom-browse').disabled=busy();
  const signature=JSON.stringify(state.custom_imports||[]);if(signature===customSignature)return;customSignature=signature;
  $('custom-list').innerHTML=(state.custom_imports||[]).length?state.custom_imports.map(item=>`<div class="custom-item"><div><strong>${escape(item.title)}</strong><small>${escape(item.author)} · ${item.parts} source part${item.parts===1?'':'s'} · ${item.available?'Saved file available':item.local_available?'Local copy available':'Source file unavailable'}</small><small>Last saved to: ${escape(item.file)}</small></div><button class="button secondary" data-custom-copy="${escape(item.id)}">Copy to folder…</button></div>`).join(''):empty('Your custom library starts here.','Add a YouTube video or playlist. Your imports and their saved locations will appear here.');
}
function openCustom(item=null){
  if(busy())return;customRequest++;customPlan=null;
  $('custom-url').value=item?.url||'';$('custom-folder').value=state.settings.folder||'';
  $('custom-preview').hidden=true;$('custom-feedback').textContent='';$('custom-count').textContent='';$('custom-start').disabled=true;
  $('custom-dialog').showModal();$('custom-url').focus();
}
$('custom-view').addEventListener('click',()=>setView('custom'));
$('custom-add').addEventListener('click',()=>openCustom());
$('custom-list').addEventListener('click',event=>{const button=event.target.closest('[data-custom-copy]');if(button)openCustom((state.custom_imports||[]).find(x=>x.id===button.dataset.customCopy));});
$('custom-close').addEventListener('click',()=>$('custom-dialog').close());
$('custom-dialog').addEventListener('close',()=>{customRequest++;$('custom-read').disabled=false;showWait('custom-feedback',false);});
$('custom-history').addEventListener('click',()=>{historyScope='custom';historyRevision=null;historySignature='';historyRuns=[];setView('history');});
$('custom-stop').addEventListener('click',()=>post('/api/stop',{}));
$('custom-browse').addEventListener('click',async()=>{
  if(busy())return;pickerPending=true;
  try{
    const response=await fetch('/api/folder',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({initial:$('custom-folder').value,library_id:state.library_id})});
    const result=await response.json();if(!response.ok)throw new Error(result.error);
    if(!result.cancelled)$('custom-folder').value=result.path;
  }catch(error){$('custom-feedback').textContent=error.message;}
  finally{pickerPending=false;refresh();}
});
$('custom-read').addEventListener('click',async()=>{
  const number=++customRequest,url=$('custom-url').value.trim(),library=state.library_id;
  showWait('custom-feedback',true,'Reading the YouTube link and checking for a local copy…');$('custom-preview').hidden=true;customPlan=null;$('custom-read').disabled=true;$('custom-count').textContent='';renderCustom();
  try{
    const response=await fetch('/api/custom/preview',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({url,folder:$('custom-folder').value.trim(),library_id:library})});
    const result=await response.json();if(number!==customRequest||!$('custom-dialog').open)return;
    if(!response.ok)throw new Error(result.error||'Could not read this link.');
    customPlan={...result,input:url,library};
    const saved=(state.custom_imports||[]).find(x=>x.id===result.source_id);
    $('custom-name').value=saved?.title||result.title;$('custom-author').value=saved?.author||result.author;$('custom-album').value=saved?.album||result.title;
    $('custom-parts').innerHTML=result.videos.map(video=>`<li>${escape(video.title)} · ${video.duration?duration(video.duration):'Duration unknown'}</li>`).join('');
    $('custom-count').textContent=`${result.videos.length} part${result.videos.length===1?'':'s'} → 1 MP3`;
    $('custom-preview').hidden=false;$('custom-feedback').textContent=result.in_destination?'Already in this destination: '+result.existing_file:result.existing_file?'Ready to copy locally from: '+result.existing_file:saved?'Previously imported: a verified local copy will be reused if available.':'Review the title, author, and destination, then add to folder.';if(result.folder_available===false)$('custom-feedback').textContent+=' Destination unavailable: connect the player or choose another folder.';renderCustom();
  }catch(error){if(number===customRequest)$('custom-feedback').textContent=error.message;}
  finally{if(number===customRequest){$('custom-read').disabled=false;showWait('custom-feedback',false);}}
});
$('custom-folder').addEventListener('input',renderCustom);
$('custom-url').addEventListener('input',renderCustom);
$('custom-url').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();$('custom-read').click();}});
$('custom-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!customPlan||busy()||$('custom-start').disabled)return;
  if(customPlan.input!==$('custom-url').value.trim()||customPlan.library!==state.library_id){$('custom-feedback').textContent='Read the link again before importing.';return;}
  const ok=await post('/api/custom/start',{plan_id:customPlan.id,folder:$('custom-folder').value.trim(),title:$('custom-name').value.trim(),author:$('custom-author').value.trim(),album:$('custom-album').value.trim()});
  if(ok){$('custom-dialog').close();setView('custom');}else $('custom-feedback').textContent=$('notice').textContent;
});
let combinePlan=null,combineOrigin=null,combineRequest=0,combineGuideStep=null;
const combineGuide = {
  link: ['combine-link-controls', 'Use this when the same story or recording is split into different parts on Spotify and YouTube. Paste the YouTube playlist for the complete recording, then click Read playlist.'],
  parts: ['combine-order', 'Check that these videos make up the complete recording and play in the right order. Pocket Sync joins them into one MP3.'],
  coverage: ['combine-coverage', 'Select only the Spotify tracks that this complete recording covers. Confirm it is the same recording, even if the two services split it differently.'],
  save: ['combine-start', 'Click Combine and add to folder when you’re ready. Pocket Sync will save one MP3 and recognize it as covering the selected Spotify tracks.']
};
function showCombineGuide(step, reveal=false) {
  combineGuideStep = step;
  $('combine-guide').hidden = !step;
  $('combine-guide-next').hidden = step !== 'parts';
  for (const [key, [id]] of Object.entries(combineGuide)) {
    $(id).classList.toggle('recording-guide-target', key === step);
  }
  if (step) {
    const [id, message] = combineGuide[step];
    $('combine-guide-text').textContent = message;
    if (reveal) {
      const target = step === 'coverage' ? $('combine-confirm') : $(id);
      target.scrollIntoView({block:'nearest'});
    }
  }
  requestRecordingSpotlight();
}
$('combine-guide-open').addEventListener('click', () => showCombineGuide(combinePlan ? 'parts' : 'link', true));
$('combine-guide-next').addEventListener('click', () => showCombineGuide($('combine-start').disabled ? 'coverage' : 'save', true));
$('combine-guide-end').addEventListener('click', () => {
  showCombineGuide(null);
  $('combine-guide-open').focus();
});
function updateCombineSelection(){
  const checked=[...document.querySelectorAll('[data-cover-track]:checked')];
  $('combine-total').textContent=combinePlan ? `${checked.length} Spotify tracks covered by one MP3` : '';
  $('combine-start').disabled=!combinePlan||!checked.length||!$('combine-confirm').checked||busy()||state.library_id!==combineOrigin||$('combine-url').value.trim()!==combinePlan.input;
  if (combineGuideStep === 'coverage' && !$('combine-start').disabled) showCombineGuide('save', true);
  if (combineGuideStep === 'save' && $('combine-start').disabled) showCombineGuide('coverage');
}
$('combine-playlist').addEventListener('click',()=>{
  combinePlan=null;combineOrigin=state.library_id;combineRequest++;
  $('combine-url').value='';$('combine-preview').hidden=true;$('combine-feedback').textContent='';$('combine-confirm').checked=false;
  updateCombineSelection();
  $('combine-dialog').showModal();$('combine-url').focus();
});
$('combine-close').addEventListener('click',()=>$('combine-dialog').close());
$('combine-dialog').addEventListener('close',()=>{combineRequest++;$('combine-inspect').disabled=false;showWait('combine-feedback',false);showCombineGuide(null);});
$('combine-inspect').addEventListener('click',async()=>{
  const url=$('combine-url').value.trim(),number=++combineRequest,library=state.library_id;
  showWait('combine-feedback',true,'Reading the playlist and checking the order of its videos…');$('combine-preview').hidden=true;combinePlan=null;$('combine-inspect').disabled=true;updateCombineSelection();
  if (combineGuideStep) showCombineGuide('link');
  try{
    const response=await fetch('/api/compilations/preview',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({url,library_id:library})});
    const result=await response.json();
    if(number!==combineRequest||!$('combine-dialog').open||library!==state.library_id)return;
    if(!response.ok)throw new Error(result.error||'Could not read the playlist.');
    combinePlan={...result,input:url};combineOrigin=library;
    $('combine-name').value=result.title;$('combine-confirm').checked=false;
    $('combine-parts').innerHTML=result.videos.map(video=>`<li>${escape(video.title)} <small>${video.duration?duration(video.duration):'Duration unknown'}</small></li>`).join('');
    $('combine-tracks').innerHTML=state.tracks.map(track=>`<label class="coverage-track"><input type="checkbox" data-cover-track="${track.id}" ${result.suggested_ids.includes(track.id)?'checked':''}><span>${escape(track.name)}<small>${escape(track.artists.join(', '))} · ${duration(track.duration)}${track.status==='present'?' · already in folder':''}</small></span></label>`).join('');
    const total=result.videos.reduce((sum,video)=>sum+(video.duration||0),0);
    $('combine-feedback').textContent=`${result.videos.length} YouTube parts · ${duration(total)} total. Review the Spotify tracks below, then confirm.`;
    $('combine-preview').hidden=false;updateCombineSelection();
    if (combineGuideStep) showCombineGuide('parts', true);
  }catch(error){if(number===combineRequest)$('combine-feedback').textContent=error.message;}
  finally{if(number===combineRequest){$('combine-inspect').disabled=false;showWait('combine-feedback',false);}}
});
$('combine-confirm').addEventListener('change',updateCombineSelection);
$('combine-tracks').addEventListener('change',updateCombineSelection);
$('combine-url').addEventListener('input',()=>{
  updateCombineSelection();
  if (combineGuideStep && $('combine-url').value.trim()!==combinePlan?.input) showCombineGuide('link');
});
$('combine-url').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();$('combine-inspect').click();}});
$('combine-form').addEventListener('submit',async event=>{
  event.preventDefault();updateCombineSelection();if($('combine-start').disabled)return;
  $('combine-start').disabled=true;
  const ok=await post('/api/compilations/start',{plan_id:combinePlan.id,title:$('combine-name').value.trim(),confirmed:$('combine-confirm').checked,ids:[...document.querySelectorAll('[data-cover-track]:checked')].map(x=>x.dataset.coverTrack)});
  if(ok){$('combine-dialog').close();setView('history');}
  else{$('combine-feedback').textContent=$('notice').textContent;updateCombineSelection();}
});
let recordingSearchNumber=0,recordingSearchAbort=null;
async function searchRecordings(){
  stopPreview();
  const query=$('recording-query').value.trim();
  if(!query){showWait('recording-status',false,'Enter an artist or song title.');return;}
  const number=++recordingSearchNumber,track=sourceTrack?.id,library=state.library_id;
  recordingSearchAbort?.abort();recordingSearchAbort=new AbortController();
  showWait('recording-status',true,'Searching YouTube for recordings…');$('recording-results').innerHTML='';
  if (!$('source-recovery').hidden) showPickerGuide('search');
  $('recording-search').disabled=true;
  try{
    const response=await fetch('/api/recordings/search',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},signal:recordingSearchAbort.signal,body:JSON.stringify({query,library_id:library})});
    const result=await response.json();
    if(number!==recordingSearchNumber||sourceTrack?.id!==track||state.library_id!==library||!$('source-dialog').open)return;
    if(!response.ok)throw new Error(result.error||'Could not search YouTube.');
    $('recording-status').textContent=result.videos.length?`${result.videos.length} recordings · Spotify duration ${duration(sourceTrack.duration)}. Select the artist and version you want.`:'No recordings found. Try another search or paste a video link below.';
    $('recording-results').innerHTML=result.videos.map(video=>{
      const mismatch=video.duration&&Math.abs(video.duration-sourceTrack.duration)>20;
      return `<article class="recording-result"><button type="button" class="recording-thumbnail" data-preview="${escape(video.id)}" aria-label="Preview ${escape(video.title)}"><img src="${escape(video.thumbnail)}" alt="" loading="lazy"><span>▶ Preview</span></button><button type="button" class="recording-choice" data-recording="${escape(video.url)}" aria-pressed="false"><span><strong>${escape(video.title)}</strong><small>${escape(video.channel)} · ${video.duration?duration(video.duration):'Duration unavailable'}</small>${mismatch?'<small class="recording-warning">Over 20 seconds different · will fail verification</small>':''}</span><span class="recording-select">Select</span></button></article>`;
    }).join('');
  }catch(error){if(error.name!=='AbortError'&&number===recordingSearchNumber)$('recording-status').textContent=error.message;}
  finally{if(number===recordingSearchNumber){
    $('recording-search').disabled=false;showWait('recording-status',false);
    if (!$('source-recovery').hidden) {
      const next = hasRecordingLink() ? 'download' : 'choose';
      showPickerGuide(next);
      const target = next === 'download' ? $('source-url')
        : $('recording-results').firstElementChild || $('source-url');
      target.scrollIntoView({block:'nearest'});
    }
  }}
}
$('recording-search').addEventListener('click',searchRecordings);
$('recording-query').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchRecordings();}});
$('recording-results').addEventListener('click',event=>{
  const preview=event.target.closest('[data-preview]');if(preview){playPreview(preview.dataset.preview);return;}
  const button=event.target.closest('[data-recording]');if(!button)return;
  $('source-url').value=button.dataset.recording;
  $('source-download').disabled=!hasRecordingLink();
  document.querySelectorAll('[data-recording]').forEach(row=>{row.setAttribute('aria-pressed',String(row===button));row.querySelector('.recording-select').textContent=row===button?'Selected':'Select';});
  $('source-feedback').style.color='var(--green)';
  $('source-feedback').textContent=matchQueue?'Recording selected. Save this match to continue to the next song.':'Recording selected. Click Download this recording when ready.';
  if (!$('source-recovery').hidden) {
    showPickerGuide('download');
    $('source-url').scrollIntoView({block:'nearest'});
  }
});
$('source-dialog').addEventListener('close',()=>{stopPreview();recordingSearchNumber++;recordingSearchAbort?.abort();$('recording-search').disabled=false;showWait('recording-status',false);showPickerGuide(null);});
$('source-recovery-end').addEventListener('click', () => {
  showPickerGuide(null);
  $('source-url').focus({preventScroll:true});
});
$('source-url').addEventListener('input',()=>{
  $('source-download').disabled=!hasRecordingLink();
  if (!$('source-recovery').hidden) showPickerGuide(hasRecordingLink() ? 'download' : 'choose');
  document.querySelectorAll('[data-recording]').forEach(row=>row.setAttribute('aria-pressed',String(row.dataset.recording===$('source-url').value.trim())));$('source-feedback').textContent='';});
$('last-sync').addEventListener('click',event=>{if(event.target.closest('[data-view-history]')){historyScope=null;historyRevision=null;setView('history');}});
$('history-stop').addEventListener('click',()=>post('/api/stop',{}));
$('history-refresh').addEventListener('click',()=>loadHistory(true));
$('history-all').addEventListener('change',()=>loadHistory(true));
$('history-list').addEventListener('click',event=>{
 const button=event.target.closest('button');if(!button||button.disabled)return;
 if(button.dataset.retry)post('/api/sync',{scan_id:state.scan_id,ids:[button.dataset.retry]});
 if(button.dataset.source)chooseSource(button.dataset.source);
});
$('source-close').addEventListener('click',()=>$('source-dialog').close());
$('source-form').addEventListener('submit',async event=>{
 event.preventDefault();
 if(!sourceTrack||busy()||!hasRecordingLink())return;
 if(matchQueue){
   if(!queueIsCurrent())return;
   matchQueue.drafts[sourceTrack.id]=$('source-url').value.trim();saveMatchDrafts();advanceMatch();return;
 }
 const button=$('source-download');button.disabled=true;
 const ok=await post('/api/sync',{scan_id:state.scan_id,ids:[sourceTrack.id],sources:{[sourceTrack.id]:$('source-url').value.trim()}});
 button.disabled=!hasRecordingLink();
 if(ok){$('source-dialog').close();if(currentView!=='history')setView('history');}
 else{$('source-feedback').style.color='';$('source-feedback').textContent=$('notice').textContent;}
});

let sidebarSignature='',editingLibraryId=null,pickerPending=false,focusHistoryJob=null;
const expandedLibraries=new Set();
function renderSidebar(){
  if(!state.libraries)return;
  const signature=JSON.stringify([state.libraries,state.library_id,currentView,busy(),[...expandedLibraries]]);
  if(signature===sidebarSignature)return;
  sidebarSignature=signature;
  $('library-nav').innerHTML=state.libraries.map(library=>{
    const selected=library.id===state.library_id,expanded=expandedLibraries.has(library.id);
    const disabled=busy()&&!selected?'disabled':'';
    const recent=library.recent_syncs||[];
    return `<div class="nav-library ${selected?'selected':''}"><div class="library-row"><button class="library-select" data-library="${library.id}" ${disabled} ${selected?'aria-current="page"':''}><span aria-hidden="true">♫</span>${escape(library.name)}</button><button class="library-expand" data-expand="${library.id}" aria-label="${expanded?'Collapse':'Expand'} ${escape(library.name)}" aria-expanded="${expanded}">${expanded?'⌃':'⌄'}</button></div><div class="library-children" ${expanded?'':'hidden'}><button class="library-history ${selected&&currentView==='history'?'active':''}" data-library-history="${library.id}" ${disabled}>↺ Sync history</button>${recent.length?recent.map(run=>`<button class="library-recent" data-library-history="${library.id}" data-history-job="${run.id}" ${disabled}>${escape(statusNames[run.status]||run.status)} · ${run.added||0} added${run.failed?' · '+run.failed+' failed':''}<time>${escape(formatTime(run.finished_at||run.started_at))}</time></button>`).join(''):'<div class="library-history-empty">No syncs yet</div>'}</div></div>`;
  }).join('');
  $('add-library').disabled=busy();
}
async function activateLibrary(id,view='library',job=null){
  historyScope=null;historyRevision=null;historySignature='';
  if(id!==state.library_id){
    if(!await post('/api/libraries/select',{id}))return;
  }
  expandedLibraries.add(id);sidebarSignature='';
  focusHistoryJob=job;
  setView(view);
}
function updateLibrarySave() {
  $('library-save').disabled = pickerPending || !$('library-name-input').value.trim() ||
    !$('library-playlist-input').validity.valid;
}
function openLibraryEditor(add=false){
  if(busy())return;
  editingLibraryId=add?null:state.library_id;
  $('library-dialog-title').textContent=add?'Add a playlist':'Library settings';
  $('library-name-input').value=add?'':state.library.name;
  $('library-playlist-input').value=add?'':state.settings.playlist;
  $('library-folder-input').value=add?'':state.settings.folder;
  $('library-folder-input').title=$('library-folder-input').value;
  $('library-folder-input').readOnly=true;
  $('library-folder-manual').textContent='Enter path manually';
  $('library-feedback').textContent='';
  $('library-save').textContent=add?'Add to library':'Save changes';
  updateLibrarySave();
  $('library-dialog').showModal();$('library-name-input').focus();
}
async function pickFolder(modal=false){
  if(requesting||pickerPending||busy())return;
  const id=state.library_id,input=$(modal?'library-folder-input':'folder');
  pickerPending=true;requesting=true;
  $('choose-folder').disabled=true;$('library-choose-folder').disabled=true;$('library-save').disabled=true;
  try{
    const response=await fetch('/api/folder',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({initial:input.value,library_id:id})});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Could not open the folder chooser.');
    if(result.cancelled)return;
    if(state.library_id!==id)throw new Error('The selected library changed. Please choose the folder again.');
    if(modal){input.value=result.path;input.title=result.path;}
    else{
      requesting=false;pickerPending=false;
      const playlist=$('playlist').value;
      if(await post('/api/libraries/update',{id,folder:result.path})){
        $('playlist').value=playlist;
        render(state);
      }
    }
  }catch(error){if(modal)$('library-feedback').textContent=error.message;else notice(error.message);}
  finally{
    requesting=false;pickerPending=false;
    $('choose-folder').disabled=false;$('library-choose-folder').disabled=false;updateLibrarySave();
    await refresh();
  }
}
function toggleManual(inputId,buttonId){
  const input=$(inputId);input.readOnly=!input.readOnly;
  $(buttonId).textContent=input.readOnly?'Enter path manually':'Use folder chooser';
  if(!input.readOnly)input.focus();
}
$('library-nav').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.expand){
    const id=button.dataset.expand;
    if(expandedLibraries.has(id))expandedLibraries.delete(id);else expandedLibraries.add(id);
    renderSidebar();
  }
  if(button.dataset.library)activateLibrary(button.dataset.library);
  if(button.dataset.libraryHistory)activateLibrary(button.dataset.libraryHistory,'history',button.dataset.historyJob||null);
});
$('add-library').addEventListener('click',()=>openLibraryEditor(true));
$('edit-library').addEventListener('click',()=>openLibraryEditor());
for(const id of ['library-close','library-cancel'])$(id).addEventListener('click',()=>$('library-dialog').close());
for (const id of ['library-name-input','library-playlist-input']) $(id).addEventListener('input', updateLibrarySave);
$('library-form').addEventListener('submit',async event=>{
  event.preventDefault();
  if(busy()||$('library-save').disabled)return;
  $('library-save').disabled=true;
  const data={name:$('library-name-input').value.trim(),playlist:$('library-playlist-input').value.trim(),folder:$('library-folder-input').value.trim()};
  if(editingLibraryId)data.id=editingLibraryId;
  const ok=await post(editingLibraryId?'/api/libraries/update':'/api/libraries/add',data);
  updateLibrarySave();
  if(ok){$('library-dialog').close();setView('library');}
  else $('library-feedback').textContent=$('notice').textContent;
});
$('choose-folder').addEventListener('click',()=>pickFolder());
$('library-choose-folder').addEventListener('click',()=>pickFolder(true));
for(const [id,modal] of [['folder',false],['library-folder-input',true]]){
  $(id).addEventListener('click',()=>{if($(id).readOnly)pickFolder(modal);});
  $(id).addEventListener('keydown',event=>{if($(id).readOnly&&['Enter',' '].includes(event.key)){event.preventDefault();pickFolder(modal);}});
}
$('folder-manual').addEventListener('click',()=>toggleManual('folder','folder-manual'));
$('library-folder-manual').addEventListener('click',()=>toggleManual('library-folder-input','library-folder-manual'));

const walkthroughSteps = [
  {
    title: 'Welcome to Pocket Sync',
    caption: 'Pocket Sync checks a public Spotify playlist against a folder on your Mac or music player. You choose which missing songs to add, and the files already in the folder stay as they are.'
  },
  {
    target: '#playlist',
    title: 'Paste a public playlist link',
    caption: 'In Spotify, open the playlist menu and choose Share → Copy link to playlist. Paste the link into the Spotify playlist field.'
  },
  {
    target: '.folder-control',
    title: 'Choose where your music goes',
    caption: 'Use Choose… to pick a folder. To sync directly to a music player, connect it first and select its folder. You can also enter the folder path manually.'
  },
  {
    target: '#check',
    title: 'Check for new songs',
    caption: 'Pocket Sync compares the playlist with the files in your folder. It lists the songs already there, the ones it can add, and possible matches to review.'
  },
  {
    target: '#library-section .tabs',
    title: 'Read the results',
    caption: 'In folder means Pocket Sync matched a file you already have. In To add, select the songs you want and choose Sync selected songs.',
    example: 'tour-comparison'
  },
  {
    title: 'Review a possible match',
    caption: 'Compare the local file with the Spotify track. If it’s the same recording, choose Use this file. If it’s a different version, you can download a separate copy.',
    example: 'tour-review'
  },
  {
    title: 'Find a recording when matching fails',
    caption: 'If an automatic download can’t find a match, open Choose recording… to search YouTube or paste a video link. Try the sample below.',
    example: 'tour-no-match'
  },
  {
    target: '#custom-view',
    title: 'Add audio from YouTube',
    caption: 'Open Custom audio → Add from YouTube… to preview a video or playlist. Pick a folder, check the parts, then choose Add to folder.',
    example: 'tour-custom'
  }
];
const walkthrough = $('walkthrough');
const walkthroughKey = 'pocket-sync-walkthrough-v2';
let walkthroughIndex = 0;
let walkthroughTarget = null;
let walkthroughReturnView;
let walkthroughReturnScroll;

function offerWalkthrough() {
  $('walkthrough-help').disabled = false;
  let seen = false;
  try { seen = localStorage.getItem(walkthroughKey) === 'seen'; } catch {}
  if (!seen) openWalkthrough();
}

function openWalkthrough() {
  walkthroughReturnView = currentView;
  walkthroughReturnScroll = window.scrollY;
  if (currentView !== 'library') setView('library');
  walkthroughIndex = 0;
  walkthrough.showModal();
  showWalkthroughStep();
}

function positionWalkthrough() {
  if (!walkthrough.open) return;
  walkthrough.classList.remove('walkthrough-anchored');
  if (!walkthroughTarget) return;

  const target = walkthroughTarget.getBoundingClientRect();
  const {width, height} = walkthrough.getBoundingClientRect();
  const gap = 14;
  const spaceBelow = window.innerHeight - target.bottom;
  const spaceAbove = target.top;
  let top;
  if (spaceBelow >= height + 2 * gap) {
    top = target.bottom + gap;
  } else if (spaceAbove >= height + 2 * gap) {
    top = target.top - height - gap;
  } else {
    return;
  }
  const left = Math.max(gap, Math.min(target.left, window.innerWidth - width - gap));
  walkthrough.style.setProperty('--walkthrough-left', left + 'px');
  walkthrough.style.setProperty('--walkthrough-top', top + 'px');
  walkthrough.classList.add('walkthrough-anchored');
}

function showWalkthroughStep() {
  const step = walkthroughSteps[walkthroughIndex];
  const first = walkthroughIndex === 0;
  const last = walkthroughIndex === walkthroughSteps.length - 1;
  walkthroughTarget?.classList.remove('walkthrough-target');
  walkthroughTarget = step.target ? document.querySelector(step.target) : null;
  walkthroughTarget?.classList.add('walkthrough-target');
  walkthroughTarget?.scrollIntoView({block: 'nearest', behavior: 'instant'});
  $('walkthrough-progress').textContent = 'Step ' + (walkthroughIndex + 1) + ' of ' + walkthroughSteps.length;
  $('walkthrough-title').textContent = step.title;
  $('walkthrough-caption').textContent = step.caption;
  const example = $('walkthrough-example');
  example.replaceChildren();
  example.hidden = !step.example;
  if (step.example) example.append($(step.example).content.cloneNode(true));
  $('walkthrough-back').hidden = first;
  $('walkthrough-next').textContent = last ? 'Done' : first ? 'Start' : 'Next';
  walkthrough.querySelector('.dialog-scroll').scrollTop = 0;
  positionWalkthrough();
  $('walkthrough-title').focus({preventScroll: true});
}

function dismissWalkthrough() {
  try { localStorage.setItem(walkthroughKey, 'seen'); } catch {}
  walkthrough.close();
}

const helpDialog = $('help-dialog');
$('help-settings').addEventListener('click', () => {
  $('reset-recording-status').textContent = '';
  loadNamingSettings();
  helpDialog.showModal();
});
$('reset-recording-guide').addEventListener('click', () => {
  recoveryGuideSeen = false;
  recoveryGuideTrack = null;
  lastGuidedTrack = null;
  try { localStorage.removeItem(recoveryGuideKey); } catch {}
  const hasFailedMatch = state?.scan_id && !busy() && !settingsChanged() &&
    state.tracks.some(row => row.status === 'missing' && row.error_code === 'no_match');
  if (!hasFailedMatch) {
    $('reset-recording-status').textContent = 'Walkthrough reset. The tip will appear in To add when a song has no automatic match.';
    if (state) showTracks();
    return;
  }
  helpDialog.close();
  $('search').value = '';
  setView('library');
  document.querySelector('[data-tab="missing"]').click();
  $('track-list').querySelector('[data-show-recovery]')?.focus();
});
$('walkthrough-help').addEventListener('click', () => {
  helpDialog.close();
  openWalkthrough();
});
$('help-library').addEventListener('click', () => {
  helpDialog.close();
  setView('library');
  openLibraryEditor();
});
$('feature-copy').addEventListener('click', async () => {
  const draft = $('feature-draft');
  const status = $('feature-status');
  try {
    await navigator.clipboard.writeText(draft.value);
    status.textContent = 'Draft copied.';
  } catch {
    draft.focus();
    draft.select();
    status.textContent = 'Press Command+C to copy the selected draft.';
  }
});
$('walkthrough-skip').addEventListener('click', dismissWalkthrough);
$('walkthrough-close').addEventListener('click', dismissWalkthrough);
walkthrough.addEventListener('cancel', event => {
  event.preventDefault();
  dismissWalkthrough();
});
$('walkthrough-back').addEventListener('click', () => {
  walkthroughIndex--;
  showWalkthroughStep();
});
$('walkthrough-next').addEventListener('click', () => {
  if (walkthroughIndex === walkthroughSteps.length - 1) {
    dismissWalkthrough();
  } else {
    walkthroughIndex++;
    showWalkthroughStep();
  }
});
walkthrough.addEventListener('close', () => {
  walkthroughTarget?.classList.remove('walkthrough-target');
  walkthroughTarget = null;
  if (currentView !== walkthroughReturnView) setView(walkthroughReturnView);
  window.scrollTo(0, walkthroughReturnScroll);
  $('help-settings').focus({preventScroll: true});
});
window.addEventListener('resize', positionWalkthrough);

document.querySelector('.brand-mark').append(loadingLogo());
showWait('status', true);
refresh();setInterval(refresh,1200);

// Manual choices remain drafts until the user submits the reviewed batch.
let matchQueue=null;
function draftKey(){return 'pocket-matches:'+JSON.stringify([state.library_id,state.settings.folder,state.settings.playlist]);}
function saveMatchDrafts(){try{localStorage.setItem(matchQueue.key,JSON.stringify(matchQueue.drafts));}catch{}}
function queueIsCurrent(){
  if(!matchQueue || matchQueue.scan!==state.scan_id || matchQueue.key!==draftKey() || busy()){
    $('source-feedback').textContent='The comparison changed. Close this chooser and check the playlist before continuing.';return false;
  }return true;
}
function stopPreview(){const host=$('recording-preview');if(host){host.replaceChildren();host.hidden=true;}}
function playPreview(id){
  if(!/^[A-Za-z0-9_-]{11}$/.test(id))return;
  stopPreview();const host=$('recording-preview');host.hidden=false;
  const frame=document.createElement('iframe');frame.title='YouTube recording preview';
  frame.src='https://www.youtube-nocookie.com/embed/'+id+'?autoplay=1&playsinline=1&origin='+encodeURIComponent(location.origin);
  frame.allow='autoplay; encrypted-media; fullscreen';frame.allowFullscreen=true;
  frame.referrerPolicy='strict-origin-when-cross-origin';
  const note=document.createElement('p');note.className='source-note';note.textContent='If YouTube cannot play this recording here, try another result or open it on YouTube.';
  const link=document.createElement('a');link.href='https://www.youtube.com/watch?v='+id;link.target='_blank';link.rel='noreferrer';link.textContent='Open on YouTube ↗';
  const close=document.createElement('button');close.type='button';close.className='button secondary';close.textContent='Stop preview';close.onclick=stopPreview;
  host.append(frame,note,link,close);host.scrollIntoView({block:'nearest'});
}
$('match-remaining').addEventListener('click',()=>{
  if(busy()||!state.scan_id||settingsChanged())return;
  const tracks=state.tracks.filter(x=>x.status!=='present' && ['no_match','verification'].includes(x.error_code));
  if(!tracks.length){notice('No failed recording matches to review. Use Choose recording on an individual song.');return;}
  let saved={};try{saved=JSON.parse(localStorage.getItem(draftKey())||'{}');}catch{}
  const ids=tracks.map(x=>x.id),drafts={};
  for(const id of ids)if(typeof saved[id]==='string'&&hasRecordingLink(saved[id]))drafts[id]=saved[id];
  matchQueue={ids,index:0,drafts,key:draftKey(),scan:state.scan_id};showQueuedMatch();
});
function showQueuedMatch(){
  if(!queueIsCurrent())return;
  if(matchQueue.index>=matchQueue.ids.length){reviewMatches();return;}
  chooseSource(matchQueue.ids[matchQueue.index],true);
  $('match-queue').hidden=false;$('match-summary').hidden=true;
  $('match-progress').textContent=`Song ${matchQueue.index+1} of ${matchQueue.ids.length} · ${Object.keys(matchQueue.drafts).length} match${Object.keys(matchQueue.drafts).length===1?'':'es'} saved`;
  $('match-back').disabled=matchQueue.index===0;$('match-skip').hidden=false;
  $('source-url').value=matchQueue.drafts[sourceTrack.id]||'';$('source-download').disabled=!hasRecordingLink();
}
function advanceMatch(){stopPreview();matchQueue.index++;showQueuedMatch();}
function reviewMatches(){
  if(!queueIsCurrent())return;
  stopPreview();recordingSearchNumber++;recordingSearchAbort?.abort();showPickerGuide(null);
  $('source-scroll').hidden=true;$('source-download').hidden=true;$('match-download').hidden=false;$('source-search').hidden=true;$('match-finish').hidden=true;
  $('match-queue').hidden=false;$('match-summary').hidden=false;$('match-skip').hidden=true;
  const entries=matchQueue.ids.filter(id=>matchQueue.drafts[id]);
  $('match-progress').textContent=`${entries.length} matched · ${matchQueue.ids.length-entries.length} left for later`;
  $('match-summary').innerHTML=matchQueue.ids.map(id=>{const track=state.tracks.find(x=>x.id===id);return `<p>${escape(track?.name)} <small>${matchQueue.drafts[id]?`<a href="${escape(matchQueue.drafts[id])}" target="_blank" rel="noreferrer">Chosen recording ↗</a>`:'Skipped'}</small><button type="button" class="button secondary" data-edit-match="${id}">Edit</button></p>`;}).join('');
  $('source-feedback').style.color='var(--muted)';
  $('match-download').disabled=!entries.length;$('match-download').textContent=`Download matched songs (${entries.length})`;
  $('match-back').disabled=false;$('source-feedback').textContent='Review your choices, then download them together.';
}
$('match-back').addEventListener('click',()=>{if(matchQueue){matchQueue.index=Math.max(0,Math.min(matchQueue.index,matchQueue.ids.length)-1);showQueuedMatch();}});
$('match-skip').addEventListener('click',()=>{if(queueIsCurrent()){delete matchQueue.drafts[sourceTrack.id];saveMatchDrafts();advanceMatch();}});
$('match-finish').addEventListener('click',reviewMatches);
$('match-summary').addEventListener('click',event=>{const button=event.target.closest('[data-edit-match]');if(button&&matchQueue){matchQueue.index=matchQueue.ids.indexOf(button.dataset.editMatch);showQueuedMatch();}});
$('match-download').addEventListener('click',async()=>{
  if(!queueIsCurrent())return;
  const ids=matchQueue.ids.filter(id=>matchQueue.drafts[id]);if(!ids.length)return;
  $('match-download').disabled=true;
  const ok=await post('/api/sync',{scan_id:matchQueue.scan,ids,sources:Object.fromEntries(ids.map(id=>[id,matchQueue.drafts[id]]))});
  if(ok){$('source-dialog').close();setView('history');}else{$('match-download').disabled=false;$('source-feedback').textContent=$('notice').textContent;}
});

let orderPlan=null;
$('playback-order').addEventListener('click',()=>{loadNamingSettings();helpDialog.showModal();$('naming-enabled').focus();});
$('naming-review').addEventListener('click',async()=>{
  if(busy())return;
  const enabled=$('naming-enabled').checked,digits=Number($('naming-digits').value);
  helpDialog.close();
  orderPlan=null;$('order-apply').disabled=true;$('order-preview').replaceChildren();$('order-status').textContent='Reading current filenames…';
  if(!$('order-dialog').open)$('order-dialog').showModal();
  const library=state.library_id,folder=state.settings.folder;
  try{
    const response=await fetch('/api/order/preview',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({library_id:library,enabled,digits})});
    const plan=await response.json();if(!response.ok)throw new Error(plan.error);
    if(!equalOrderContext(library,folder)||!$('order-dialog').open)return;
    orderPlan={...plan,library,originFolder:folder};$('order-folder').textContent=plan.folder;
    $('order-title').textContent=plan.enabled?'Numbered filenames':'Simple filenames';
    $('order-status').textContent=!plan.enabled?'Future additions will use Artist - Title.mp3. Existing filenames will stay unchanged.':plan.changes.length?`${plan.changes.length} files will be numbered in the order shown.`:'No filenames need to change. Save to use this preference for future additions.';
    $('order-preview').innerHTML=plan.changes.map(x=>`<li><strong>${escape(x.new)}</strong><small>Previously ${escape(x.old)}</small></li>`).join('');
    $('order-apply').disabled=false;
  }catch(error){$('order-status').textContent=error.message;}
});
function equalOrderContext(library,folder){return state.library_id===library&&state.settings.folder===folder&&!busy();}
$('order-close').addEventListener('click',()=>$('order-dialog').close());
$('order-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!orderPlan||!equalOrderContext(orderPlan.library,orderPlan.originFolder)){$('order-status').textContent='The library changed. Close and preview again.';return;}
  $('order-apply').disabled=true;
  try{
    const response=await fetch('/api/order/apply',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':token},body:JSON.stringify({library_id:orderPlan.library,plan_id:orderPlan.id})});
    const result=await response.json();if(!response.ok)throw new Error(result.error);
    $('order-status').textContent=result.enabled?`${result.renamed} filenames updated. Future additions use ${result.digits}-digit numbers.`:'Saved. Future additions use simple filenames without numbers.';
    $('order-preview').replaceChildren();orderPlan=null;await refresh();
  }catch(error){$('order-status').textContent=error.message+' Preview again before retrying.';orderPlan=null;}
});

function loadNamingSettings(){
  const naming=state.naming||{enabled:false,digits:3};
  $('naming-enabled').checked=naming.enabled;$('naming-digits').value=String(naming.digits);
  $('naming-folder').textContent=state.settings.folder||'Choose a destination folder first.';
  $('naming-status').textContent=naming.error||'';
  $('naming-review').disabled=busy()||!state.folder_available||!state.settings.folder;
  updateNamingOptions();
}
function updateNamingOptions(){
  $('naming-options').hidden=!$('naming-enabled').checked;
  const digits=Number($('naming-digits').value);
  $('naming-example').textContent=`Example: ${String(1).padStart(digits,'0')} - Artist - Title.mp3. Supports up to ${10**digits-1} numbered files.`;
}
$('naming-enabled').addEventListener('change',updateNamingOptions);
$('naming-digits').addEventListener('change',updateNamingOptions);
