"""User-confirmed multi-part recordings, with portable Spotify coverage tags."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import subprocess
import threading
import time
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen
import uuid

from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TPE2, TALB, TRCK, TDRC, APIC, TXXX, WOAS
from playlist_sync.history import timestamp, read_log

TAG = 'PocketSync confirmed coverage'


def youtube_runtime_args():
    deno = shutil.which('deno') or Path.home()/'.spotdl'/'deno'
    if Path(deno).is_file():
        return ['--js-runtimes', 'deno:'+str(deno)]
    node = shutil.which('node')
    return ['--js-runtimes', 'node:'+node] if node else []


def coverage(audio):
    """Only honor explicit coverage on intact tagged audio of the saved length."""
    try:
        tag = audio.tags.get('TXXX:'+TAG)
        data = json.loads(tag.text[0])
        ids = data['track_ids']
        if data.get('version') != 1 or data.get('confirmed') is not True:
            return set()
        if not isinstance(ids, list) or not ids or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9]{22}',x) for x in ids):
            return set()
        if abs(audio.info.length-data['duration']) > 3:
            return set()
        if not all(str(audio.tags.get(key,'')).strip() for key in ('TIT2','TPE1','TALB','TRCK','TDRC')) or not any(x.data for x in audio.tags.getall('APIC')):
            return set()
        return set(ids)
    except (AttributeError, KeyError, ValueError, TypeError, IndexError):
        return set()


def playlist_url(value):
    parsed = urlparse(str(value).strip())
    if parsed.scheme != 'https' or parsed.hostname not in ('youtube.com','www.youtube.com','music.youtube.com'):
        raise ValueError('Paste an https YouTube playlist or video-with-playlist link.')
    ident = parse_qs(parsed.query).get('list',[''])[0]
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,100}',ident):
        raise ValueError('This YouTube link has no playlist ID.')
    return 'https://www.youtube.com/playlist?list='+ident


def inspect_playlist(engine, value, custom=False):
    from playlist_sync.library import normalize
    with engine.lock:
        engine._require_unlocked() if custom else engine.require_ready()
        library, scan = engine.library_id, engine.state['scan_id']
    if custom and not parse_qs(urlparse(str(value)).query).get('list'):
        from playlist_sync.history import youtube_url
        url = youtube_url(str(value))
    else:
        url = playlist_url(value)
    try:
        result = subprocess.run([sys.executable,'-m','yt_dlp','--ignore-config','--flat-playlist','--dump-single-json',
                                 '--skip-download','--no-warnings',*youtube_runtime_args(),'--playlist-end','101','--socket-timeout','10',
                                 '--retries','0','--extractor-retries','0','--',url],capture_output=True,text=True,timeout=45)
    except subprocess.TimeoutExpired as error:
        raise ValueError('Reading the YouTube playlist timed out. Try again.') from error
    if result.returncode:
        raise ValueError('Could not read this YouTube playlist. It must be public and available.')
    try:
        data = json.loads(result.stdout)
        entries = data.get('entries') or ([data] if custom and data.get('id') else [])
        if not 1 <= len(entries) <= 100:
            raise ValueError('Choose a playlist containing 1–100 parts.')
        videos = []
        for item in entries:
            if not item or not re.fullmatch(r'[A-Za-z0-9_-]{11}',str(item.get('id',''))) or item.get('is_live') or item.get('live_status') in ('is_live','is_upcoming'):
                raise ValueError('The playlist contains an unavailable or live part. Choose another playlist.')
            videos.append({'id':item['id'],'title':str(item.get('title') or 'Untitled part')[:300],
                           'duration':item.get('duration') if isinstance(item.get('duration'),(int,float)) else None,
                           'channel':str(item.get('channel') or item.get('uploader') or '')[:150],
                           'url':'https://www.youtube.com/watch?v='+item['id']})
    except (TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError('YouTube returned an unreadable playlist.') from error
    title = str(data.get('title') or 'Combined recording')[:150]
    def base(name):
        return normalize(re.sub(r',?\s*(?:pt\.?|part)\s*\d+.*$','',name,flags=re.I))
    with engine.lock:
        engine._require_unlocked() if custom else engine.require_ready()
        if engine.library_id != library or engine.state['scan_id'] != scan:
            raise ValueError('The comparison changed. Inspect the playlist again.')
        plan = {'id':uuid.uuid4().hex,'url':url,'title':title,'videos':videos,'library_id':library,'scan_id':scan,
                'created':time.time(),'suggested_ids':[s['song_id'] for s in engine.songs if base(s['name'])==base(title)]}
        if custom:
            plan['author']=str(data.get('channel') or data.get('uploader') or videos[0].get('channel') or '')[:150]
            plan['source_id']=hashlib.sha256(json.dumps([x['id'] for x in videos]).encode()).hexdigest()[:22]
            engine.custom_plan=plan
        else:
            engine.compilation_plan = plan
        return copy.deepcopy(plan)


def start_compilation(engine, data):
    from playlist_sync.engine import ensure_folder
    with engine.lock:
        engine.require_ready()
        plan = getattr(engine,'compilation_plan',None)
        if not plan or data.get('plan_id') != plan['id'] or engine.library_id != plan['library_id'] or engine.state['scan_id'] != plan['scan_id'] or time.time()-plan['created'] > 1800:
            raise ValueError('Inspect the YouTube playlist again before combining.')
        if data.get('confirmed') is not True:
            raise ValueError('Confirm that this playlist covers the selected Spotify tracks.')
        ids = data.get('ids')
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or not set(ids) <= {s['song_id'] for s in engine.songs}:
            raise ValueError('Select the Spotify tracks covered by this recording.')
        title = str(data.get('title') or plan['title']).strip()
        if not 1 <= len(title) <= 150:
            raise ValueError('Enter a title between 1 and 150 characters.')
        if not shutil.which('ffmpeg'):
            raise ValueError('FFmpeg is required to combine recordings.')
        ensure_folder(engine.folder,engine.identity)
        duration = sum(x['duration'] or 0 for x in plan['videos'])
        needed = max(duration,3600)*40000+20000000
        if any(shutil.disk_usage(folder).free < needed for folder in (engine.folder,engine.runtime)):
            raise ValueError('There is not enough free space to download and combine this playlist.')
        songs = list({s['song_id']:copy.deepcopy(s) for s in engine.songs if s['song_id'] in ids}.values())
        run = {'version':2,'id':uuid.uuid4().hex,'kind':'combined','started_at':timestamp(),'finished_at':None,
               'folder':str(engine.folder),'playlist_name':engine.state.get('playlist_name'),'playlist_url':engine.state['settings']['playlist'],
               'library_id':engine.library_id,'library_name':engine.libraries.get()['name'],'status':'running',
               'message':'Downloading and combining playlist parts.','added':0,'errors':[],
               'items':[{'id':s['song_id'],'name':s['name'],'artists':s['artists'],'url':s['url'],'status':'queued',
                         'verified':False,'method':'combined','source_url':plan['url'],'log_track':songs[0]['song_id'],
                         'message':'Waiting for the complete combined recording.'} for s in songs]}
        engine.cancel.clear()
        engine.history.save(run)
        engine.update(phase='syncing',job_id=run['id'],current_id=None,errors=[],log=[],last_sync=engine.run_summary(run),
                      message='Downloading playlist parts…',progress={'done':0,'total':len(plan['videos']),'added':0,'failed':0})
        engine.worker=threading.Thread(target=combine_worker,args=(engine,copy.deepcopy(plan),songs,title,run),daemon=True)
        engine.worker.start()


def combine_worker(engine, plan, songs, title, run):
    from playlist_sync.engine import atomic_json, ensure_folder, install_file
    job = engine.runtime/run['id']; stage=job/songs[0]['song_id'];stage.mkdir(parents=True)
    folder=Path(run['folder']);identity=run.get('_destination_identity',engine.identity)
    custom=run.get('kind')=='custom'
    logpath=stage/'download.log'
    parts=[]; destination=None
    def checkpoint():
        engine.history.save(run)
        if not custom:engine.update(last_sync=engine.run_summary(run))
    try:
        for item in run['items']:item.update(status='downloading',started_at=timestamp())
        checkpoint()
        if custom and plan.get('reuse_master'):
            cached=Path(plan['reuse_master'])
            if import_identity(MP3(cached))!=plan['source_id']:raise ValueError('The local recording changed. Read the link again.')
            masterdir=engine.runtime/'combined'/run['id'];masterdir.mkdir(parents=True)
            filename=re.sub(r'[\x00-\x1f/\\:*?"<>|]','_',songs[0]['artists'][0]+' - '+title).strip(' .')[:180]+'.mp3'
            local=masterdir/filename;shutil.copyfile(cached,local)
            audio=MP3(local)
            for frame in (TIT2(text=title),TPE1(text=songs[0]['artists']),TPE2(text=songs[0]['artists']),TALB(text=songs[0]['album_name'])):audio.tags.add(frame)
            audio.save(v2_version=3)
            finish_custom_copy(engine,plan,songs,title,run,local,folder,identity)
            return
        for index,video in enumerate(plan['videos']):
            if engine.cancel.is_set():raise InterruptedError('Combined download stopped. No tracks were marked complete.')
            ensure_folder(folder,identity)
            engine.update(message=f"Downloading part {index+1} of {len(plan['videos'])}: {video['title']}")
            part=stage/f'part-{index:03}.mp3';partlog=stage/f'part-{index:03}.log'
            code=engine.run_process([sys.executable,'-m','yt_dlp','--ignore-config',*youtube_runtime_args(),'--no-playlist','-f','bestaudio',
                                     '-x','--audio-format','mp3','--audio-quality','128K','--socket-timeout','20','--retries','1',
                                     '--extractor-retries','1','-o',str(part.with_suffix('.%(ext)s')),'--',video['url']],300,partlog)
            with logpath.open('a') as log:log.write(f"\nPart {index+1}: {video['url']}\n"+read_log(partlog))
            if code or not part.exists():raise ValueError(f'Part {index+1} could not be downloaded. See the saved log; no tracks were marked complete.')
            audio=MP3(part)
            if audio.info.length <= 0 or (video['duration'] and abs(audio.info.length-video['duration'])>10):
                raise ValueError(f'Part {index+1} did not pass its audio duration check.')
            parts.append(part)
            engine.update(progress={'done':index+1,'total':len(plan['videos']),'added':0,'failed':0})
        engine.update(message='Combining and tagging the complete recording…')
        listing=stage/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in parts))
        combined=stage/'combined.mp3'
        code=engine.run_process(['ffmpeg','-v','error','-f','concat','-safe','1','-i',str(listing),'-c:a','libmp3lame','-b:a','128k',str(combined)],180,stage/'combine.log')
        if code:raise ValueError('The audio parts could not be combined. No tracks were marked complete.')
        length=sum(MP3(p).info.length for p in parts);audio=MP3(combined)
        if abs(audio.info.length-length)>3:raise ValueError('The combined file is incomplete. No tracks were marked complete.')
        first=songs[0];cover=first.get('cover_url','')
        if urlparse(cover).scheme!='https' or urlparse(cover).hostname not in (('i.ytimg.com',) if custom else ('i.scdn.co',)):raise ValueError('Cover art is unavailable for this recording.')
        with urlopen(cover,timeout=25) as response:art=response.read(10000001)
        if not art or len(art)>10000000:raise ValueError('Could not retrieve usable cover art.')
        from PIL import Image
        import io
        image=Image.open(io.BytesIO(art));image.verify()
        if audio.tags is None:audio.add_tags()
        for frame in (TIT2(text=title),TPE1(text=first['artists']),TPE2(text=first.get('album_artist') or first['artists']),
                      TALB(text=first['album_name']),TRCK(text='1'),
                      APIC(mime='image/png' if art.startswith(b'\x89PNG') else 'image/jpeg',type=3,data=art),WOAS(url=plan['url'])):
            audio.tags.add(frame)
        if first.get('date') or first.get('year') or not custom:
            audio.tags.add(TDRC(text=str(first.get('date') or first.get('year') or '2000')))
        metadata={'version':1,'confirmed':True,'track_ids':[s['song_id'] for s in songs],'duration':audio.info.length,
                  'source_playlist':plan['url'],'parts':plan['videos'],'confirmed_at':timestamp()}
        if custom:metadata.update(source_id=plan['source_id'])
        audio.tags.add(TXXX(desc=CUSTOM_TAG if custom else TAG,text=json.dumps(metadata,ensure_ascii=False)));audio.save(v2_version=3)
        if (custom and import_identity(MP3(combined))!=plan['source_id']) or (not custom and coverage(MP3(combined))!=set(metadata['track_ids'])):raise ValueError('Could not verify the combined recording metadata.')
        if engine.cancel.is_set():raise InterruptedError('Combined download stopped before copying.')
        ensure_folder(folder,identity)
        filename=re.sub(r'[\x00-\x1f/\\:*?"<>|]','_',', '.join(first['artists'])+' - '+title).strip(' .')[:180]+'.mp3'
        masterdir=engine.runtime/'combined'/run['id'];masterdir.mkdir(parents=True)
        master=masterdir/filename;shutil.copyfile(combined,master)
        atomic_json(masterdir/'coverage.json',metadata)
        if custom:
            finish_custom_copy(engine,plan,songs,title,run,master,folder,identity)
            for part in parts:part.unlink(missing_ok=True)
            combined.unlink(missing_ok=True)
            return
        for song in songs:engine.reuse.remember(song['song_id'],master)
        destination=install_file(master,folder,identity,filename=filename)
        for item in run['items']:
            item.update(status='covered',verified=True,file=str(destination),source_file=str(master),finished_at=timestamp(),
                        message='Covered by one combined recording, confirmed by you. Individual Spotify durations may differ.')
            engine.reuse.remember(item['id'],master);engine.reuse.remember(item['id'],destination)
        run.update(status='completed',added=1,message=f"1 combined MP3 added; {len(songs)} Spotify tracks covered.")
        for part in parts:part.unlink(missing_ok=True)
        combined.unlink(missing_ok=True)
    except Exception as error:
        run.update(status='stopped' if isinstance(error,InterruptedError) else 'failed',message=str(error),errors=[str(error)])
        for item in run['items']:item.update(status='stopped' if isinstance(error,InterruptedError) else 'failed',message=str(error),finished_at=timestamp())
    finally:
        run['finished_at']=timestamp();checkpoint()
        try:
            if engine.folder is not None:engine.refresh_local()
        except (ValueError,OSError):pass
        engine.update(phase='ready' if run['status']=='completed' or run['status']=='stopped' else 'error',message=run['message'],current_id=None,
                      errors=run['errors'],progress={'done':len(plan['videos']) if run['status']=='completed' else len(parts),'total':len(plan['videos']),'added':run['added'],'failed':int(run['status']=='failed')})


CUSTOM_TAG = 'PocketSync custom audio'


def import_identity(audio):
    try:
        data=json.loads(audio.tags['TXXX:'+CUSTOM_TAG].text[0])
        if data.get('version')!=1 or not re.fullmatch(r'[a-f0-9]{22}',data.get('source_id','')):return None
        if abs(audio.info.length-data['duration'])>3 or audio.info.length<=0:return None
        if not all(str(audio.tags.get(k,'')).strip() for k in ('TIT2','TPE1','TALB','TRCK')) or not any(x.data for x in audio.tags.getall('APIC')):return None
        return data['source_id']
    except (AttributeError,KeyError,ValueError,TypeError,IndexError):
        try:
            if not coverage(audio):return None
            previous=json.loads(audio.tags['TXXX:'+TAG].text[0]);ids=[p['id'] for p in previous['parts']]
            if not ids or any(not re.fullmatch(r'[A-Za-z0-9_-]{11}',x) for x in ids):return None
            return hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:22]
        except (AttributeError,KeyError,ValueError,TypeError,IndexError):return None


def custom_catalog(engine):
    try:return json.loads((engine.runtime/'custom-audio.json').read_text())
    except (ValueError,OSError):return {}


def custom_snapshot(engine):
    rows=[]
    for ident,item in custom_catalog(engine).items():
        rows.append({**item,'id':ident,'available':Path(item.get('file','')).is_file(),
                     'local_available':Path(item.get('master','')).is_file()})
    return rows


def find_custom(engine,ident,folder):
    from playlist_sync.library import scan_folder
    item=custom_catalog(engine).get(ident,{})
    roots=[folder]+[Path(x) for x in engine.reuse.data['folders'] if x!=str(folder)]
    # Prefer the selected destination, then remembered sources and the local master.
    for root in roots:
        if root.is_dir():
            for track in scan_folder(root):
                if track.import_id==ident:return track.path
    for value in [item.get('master'),item.get('file'),*engine.runtime.glob('combined/*/*.mp3')]:
        if not value:continue
        path=Path(value)
        try:
            if not path.is_symlink() and import_identity(MP3(path))==ident:return path
        except Exception:continue
    return None


def start_custom(engine,data):
    from playlist_sync.engine import folder_identity
    from playlist_sync.libraries import validate_folder
    with engine.lock:
        engine._require_unlocked();plan=copy.deepcopy(getattr(engine,'custom_plan',None))
        if not plan or data.get('plan_id')!=plan['id'] or time.time()-plan['created']>1800 or plan['library_id']!=engine.library_id:
            raise ValueError('Read the YouTube link again before importing.')
        folder_value=validate_folder(data.get('folder',''))
        if not folder_value:raise ValueError('Choose a destination folder.')
        folder=Path(folder_value);identity=folder_identity(folder)
        title=str(data.get('title','')).strip();author=str(data.get('author','')).strip();album=str(data.get('album') or title).strip()
        if any(not 1<=len(x)<=150 for x in (title,author,album)):raise ValueError('Enter a title, author, and album between 1 and 150 characters.')
        source=find_custom(engine,plan['source_id'],folder)
        if source and (source==folder or folder in source.parents):raise ValueError('This recording is already in the selected destination. No duplicate was added.')
        if source:plan['reuse_master']=str(source)
        if not source and not shutil.which('ffmpeg'):raise ValueError('FFmpeg is required to import audio.')
        needed=max(sum(x['duration'] or 0 for x in plan['videos']),3600)*40000+20000000
        if any(shutil.disk_usage(p).free<needed for p in (folder,engine.runtime)):raise ValueError('There is not enough free space to import this recording.')
        song={'song_id':plan['source_id'],'name':title,'artists':[author],'album_artist':author,'album_name':album,
              'url':plan['url'],'cover_url':'https://i.ytimg.com/vi/'+plan['videos'][0]['id']+'/hqdefault.jpg'}
        run={'version':2,'id':uuid.uuid4().hex,'kind':'custom','started_at':timestamp(),'finished_at':None,
             'folder':str(folder),'_destination_identity':identity,'playlist_name':title,'playlist_url':None,
             'library_id':'custom','library_name':'Custom audio','status':'running','message':'Importing custom audio.',
             'added':0,'errors':[],'items':[{'id':plan['source_id'],'name':title,'artists':[author],'url':plan['url'],
                 'status':'queued','verified':False,'method':'custom','source_url':plan['url'],'message':'Waiting to import.'}]}
        engine.cancel.clear();engine.history.save(run)
        engine.update(phase='syncing',job_id=run['id'],message='Importing custom audio…',current_id=None,errors=[],log=[],
                      progress={'done':0,'total':len(plan['videos']),'added':0,'failed':0})
        engine.worker=threading.Thread(target=combine_worker,args=(engine,plan,[song],title,run),daemon=True);engine.worker.start()


def finish_custom_copy(engine,plan,songs,title,run,master,folder,identity):
    from playlist_sync.engine import atomic_json,install_file
    if import_identity(MP3(master))!=plan['source_id']:raise ValueError('The local recording no longer passes verification. Read the link again.')
    if engine.cancel.is_set():raise InterruptedError('Custom import stopped before copying.')
    # Recheck for a file added externally while the download was running.
    from playlist_sync.library import scan_folder
    present=next((x.path for x in scan_folder(folder) if x.import_id==plan['source_id']),None)
    destination=present or install_file(master,folder,identity,filename=master.name)
    song=songs[0];catalog=custom_catalog(engine)
    catalog[plan['source_id']]={'title':str(MP3(master).tags['TIT2']),'author':str(MP3(master).tags['TPE1']),
        'album':str(MP3(master).tags['TALB']),'url':plan['url'],'master':str(master),'file':str(destination),
        'parts':len(plan['videos']),'updated_at':timestamp()}
    atomic_json(engine.runtime/'custom-audio.json',catalog);engine.reuse.register(folder)
    run['items'][0].update(status='already_present' if present else 'added',verified=True,file=str(destination),
        source_file=str(master),method='local_copy' if plan.get('reuse_master') else 'custom',finished_at=timestamp(),
        message='Already in destination; no duplicate added.' if present else 'Custom audio copied and verified, with cover art and tags.')
    run.update(status='completed',added=0 if present else 1,message='Already in destination.' if present else '1 custom recording added; no Spotify link required.')
    with (engine.runtime/run['id']/song['song_id']/'download.log').open('a') as log:log.write('\nCustom audio saved to: '+str(destination)+'\n')
