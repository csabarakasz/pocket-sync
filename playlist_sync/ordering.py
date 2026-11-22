"""Opt-in filename numbering for players that sort their All songs list by name."""
import json
import os
from pathlib import Path
import re
import uuid
import sys
import unicodedata

from playlist_sync.playback import AUDIO, update_playlist

STATE = '.pocketsync-filename-order.json'
NUMBER = re.compile(r'^(\d{1,9}) - ')


def rename_file(source, destination):
    # FAT's rename lookup can require the stored Unicode form, even though
    # stat/read accept equivalent forms. Different files may use different forms.
    candidates=[Path(source)]
    if sys.platform == 'darwin':
        candidates += [Path(unicodedata.normalize(form,str(source))) for form in ('NFC','NFD')]
    for candidate in dict.fromkeys(candidates):
        try:
            return candidate.rename(destination)
        except FileNotFoundError:
            failure=sys.exc_info()[1]
    raise failure


def files(folder):
    return sorted((p for p in Path(folder).iterdir() if p.is_file() and not p.is_symlink()
                   and not p.name.startswith('.') and p.suffix.lower() in AUDIO), key=lambda p:p.name.casefold())


def load(folder):
    path=Path(folder)/STATE
    if not path.exists(): return None
    try:
        data=json.loads(path.read_text())
        if data.get('version') != 1: raise ValueError
        return data
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('The playback numbering record is unreadable. Restore its backup before adding music.') from error


def save(folder, data):
    temporary=Path(folder)/('.pocketsync-order-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        temporary.replace(Path(folder)/STATE)
    finally: temporary.unlink(missing_ok=True)


def validate_digits(digits):
    if type(digits) is not int or not 1 <= digits <= 6:
        raise ValueError('Choose between 1 and 6 numbering digits.')
    return digits


def preference(folder):
    state=load(folder) if folder and Path(folder).is_dir() else None
    return {'enabled':bool(state and state.get('enabled',True)),
            'digits':validate_digits(state.get('digits',3)) if state else 3}


def preview(folder, digits=None, enabled=True):
    if type(enabled) is not bool: raise ValueError('Numbering must be enabled or disabled.')
    folder=Path(folder);state=load(folder);entries=files(folder)
    digits=validate_digits(digits if digits is not None else (state.get('digits',3) if state else 3))
    maximum=max([int(state.get('last_number',0)) if state else 0]+[int(NUMBER.match(p.name)[1]) for p in entries if state and NUMBER.match(p.name)])
    if enabled and maximum>=10**digits:
        raise ValueError(f'{digits}-digit numbering supports up to {10**digits-1} songs. Choose more digits.')
    changes=[]
    for path in entries if enabled else []:
        existing=NUMBER.match(path.name) if state else None
        if existing:
            number=int(existing[1])
            original_title=NUMBER.sub('',path.name)
        else:
            maximum+=1
            number=maximum
            original_title=re.sub(r'^\d+[_ .-]+','',path.name)
        if number>=10**digits: raise ValueError(f'{digits}-digit numbering supports up to {10**digits-1} songs. Choose more digits.')
        name=f'{number:0{digits}d} - {original_title}'
        if len(name.encode('utf-16-le'))//2 > 240:
            raise ValueError('A filename is too long to add a playback number: '+path.name)
        if name==path.name: continue
        stat=path.stat()
        changes.append({'old':path.name,'new':name,'signature':[stat.st_size,stat.st_mtime_ns,stat.st_ino]})
    return {'version':1,'changes':changes,'last_number':maximum,'enabled':enabled,'digits':digits,'previous_enabled':bool(state and state.get('enabled',True))}


def apply(folder, plan, ensure):
    """Stage names with a durable journal; refuse stale previews and overwrites."""
    folder=Path(folder);ensure()
    if preview(folder,plan['digits'],plan['enabled'])!=plan: raise ValueError('The folder changed. Preview the playback order again.')
    previous=load(folder)
    changes=plan['changes']
    targets={x['new'] for x in changes}
    if len(targets)!=len(changes) or any((folder/name).exists() for name in targets):
        raise ValueError('A numbered filename already exists. No files were renamed.')
    journal={'version':1,'status':'pending','changes':changes,'previous':previous,
             'staged':{x['old']:'.pocketsync-rename-'+uuid.uuid4().hex+'.tmp' for x in changes}}
    journal_path=folder/('.pocketsync-order-rollback-'+uuid.uuid4().hex+'.json')
    journal_path.write_text(json.dumps(journal,ensure_ascii=False,indent=2))
    moved=[]
    try:
        for change in changes:
            ensure();old=folder/change['old'];stage=folder/journal['staged'][change['old']]
            rename_file(old,stage);moved.append((change,stage))
        for change,stage in moved:
            ensure();destination=folder/change['new']
            # Exclusive reservation prevents an unrelated concurrent file from being overwritten.
            fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644);os.close(fd)
            try: stage.replace(destination)
            except BaseException:
                destination.unlink(missing_ok=True);raise
        state={'version':1,'last_number':plan['last_number'],'rollback':journal_path.name,'enabled':plan['enabled'],'digits':plan['digits']}
        save(folder,state)
        # Rewrite known playlist paths before its normal reconciliation.
        from playlist_sync.playback import PLAYLIST
        playlist=folder/PLAYLIST
        if playlist.exists():
            mapping={x['old']:x['new'] for x in changes}
            lines=playlist.read_text(encoding='utf-8-sig').splitlines()
            playlist.write_text('\n'.join(mapping.get(x,x) for x in lines)+'\n',encoding='utf-8')
        update_playlist(folder)
        journal['status']='completed';journal_path.write_text(json.dumps(journal,ensure_ascii=False,indent=2))
    except BaseException:
        # Do not access a replacement mount if the player disappeared.
        ensure()
        for change,stage in reversed(moved):
            source=stage if stage.exists() else folder/change['new']
            if source.exists() and not (folder/change['old']).exists(): rename_file(source,folder/change['old'])
        if previous is None: (folder/STATE).unlink(missing_ok=True)
        else: save(folder,previous)
        journal['status']='rolled_back';journal_path.write_text(json.dumps(journal,ensure_ascii=False,indent=2))
        raise
    return {x['old']:x['new'] for x in changes},journal_path


def next_filename(folder, name):
    state=load(folder)
    if not state or not state.get('enabled',True): return name
    pending=preview(folder)
    if pending['changes']:
        raise ValueError('Unnumbered music was added outside Pocket Sync. Review playback numbering before syncing.')
    highest=pending['last_number']+1
    digits=validate_digits(state.get('digits',3))
    if highest>=10**digits: raise ValueError(f'{digits}-digit numbering supports up to {10**digits-1} songs. Choose more digits.')
    return f'{highest:0{digits}d} - {NUMBER.sub("",name)}'


def remember_number(folder, name):
    state=load(folder)
    if state and NUMBER.match(name):
        state['last_number']=max(state['last_number'],int(NUMBER.match(name)[1]));save(folder,state)


def rewrite_references(runtime, folder, mapping):
    """Keep match confirmations, reuse pointers and history links valid after renames."""
    import shutil
    runtime=Path(runtime);folder=Path(folder)
    absolute={str(folder/old):str(folder/new) for old,new in mapping.items()}
    backup=runtime/('order-reference-backup-'+uuid.uuid4().hex);backup.mkdir()
    paths=[runtime/'matches.json',runtime/'local-files.json',runtime/'custom-audio.json']+list(runtime.glob('*/history.json'))
    def rewrite(value):
        if isinstance(value,str): return absolute.get(value,value)
        if isinstance(value,list): return [rewrite(x) for x in value]
        if isinstance(value,dict): return {key:rewrite(item) for key,item in value.items()}
        return value
    for path in paths:
        if not path.exists(): continue
        original=json.loads(path.read_text());updated=rewrite(original)
        if path.name=='matches.json':
            for match in updated.get(str(folder),{}).values():
                if match.get('file') in mapping: match['file']=mapping[match['file']]
        if original!=updated:
            relative=path.relative_to(runtime);saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,saved)
            temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2));temporary.replace(path)
    return backup


def restore(folder, journal_path, ensure):
    """Undo the most recent migration before any later songs have been added."""
    folder=Path(folder);journal_path=Path(journal_path);ensure()
    journal=json.loads(journal_path.read_text());state=load(folder)
    if journal.get('status')!='completed' or not state or state.get('rollback')!=journal_path.name:
        raise ValueError('Only the latest completed numbering migration can be undone.')
    changes=journal['changes'];expected={x['new'] for x in changes}
    previous=journal.get('previous')
    if previous is not None:
        raise ValueError('This migration adopted additional files. Use its saved mapping to review restoration separately.')
    if {x.name for x in files(folder)}!=expected:
        raise ValueError('Music was added or removed after numbering. Review restoration before changing names.')
    if any((folder/x['old']).exists() for x in changes): raise ValueError('An original filename is already occupied.')
    for change in changes:
        stat=(folder/change['new']).stat()
        if [stat.st_size,stat.st_mtime_ns]!=change['signature'][:2]:
            raise ValueError('A numbered file changed after migration. Review restoration first.')
    for change in changes:
        ensure();rename_file(folder/change['new'],folder/change['old'])
    (folder/STATE).unlink()
    from playlist_sync.playback import PLAYLIST
    playlist=folder/PLAYLIST
    if playlist.exists():
        reverse={x['new']:x['old'] for x in changes}
        playlist.write_text('\n'.join(reverse.get(x,x) for x in playlist.read_text(encoding='utf-8-sig').splitlines())+'\n',encoding='utf-8')
    journal['status']='restored';journal_path.write_text(json.dumps(journal,ensure_ascii=False,indent=2))
    return {x['new']:x['old'] for x in changes}
