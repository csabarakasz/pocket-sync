"""Saved playlist/destination pairs and a native macOS folder chooser."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import plistlib
import shutil
import sys
import time
import uuid

from download import spotify_link


def playlist_url(value):
    try:
        link = spotify_link(str(value))
    except argparse.ArgumentTypeError as error:
        raise ValueError(str(error)) from error
    if '/playlist/' not in link:
        raise ValueError('Use a Spotify playlist link for a library.')
    return link


def validate_folder(value):
    value = str(value).strip()
    if not value:
        return ''
    folder = Path(value).expanduser().absolute()
    if not folder.is_dir():
        raise ValueError('Choose an existing folder, or create one in the folder chooser.')
    return str(folder)


class LibraryStore:
    def __init__(self, runtime, previous):
        self.path = Path(runtime)/'libraries.json'
        try:
            self.data = json.loads(self.path.read_text())
            if not self.data.get('libraries') or self.data.get('active_id') not in {x['id'] for x in self.data['libraries']}:
                raise ValueError('Invalid saved libraries')
        except (OSError, ValueError, KeyError, TypeError):
            library = {'id': uuid.uuid4().hex, 'name': 'Your music',
                       'playlist': previous['playlist'], 'folder': previous['folder'], 'updated_at': time.time_ns()}
            self.data = {'version': 1, 'active_id': library['id'], 'libraries': [library]}
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        temporary.replace(self.path)

    def list(self):
        return copy.deepcopy(self.data['libraries'])

    def get(self, library_id=None):
        library_id = library_id or self.data['active_id']
        library = next((x for x in self.data['libraries'] if x['id'] == library_id), None)
        if library is None:
            raise ValueError('Library not found.')
        return copy.deepcopy(library)

    def select(self, library_id):
        library = self.get(library_id)
        self.data['active_id'] = library_id
        self.save()
        return library

    def add(self, name, playlist, folder=''):
        name = str(name).strip()
        if not 1 <= len(name) <= 80:
            raise ValueError('Give this library a name between 1 and 80 characters.')
        url = playlist_url(playlist)
        if any(x['playlist'] == url for x in self.data['libraries']):
            raise ValueError('That playlist is already saved in Your Library.')
        library = {'id': uuid.uuid4().hex, 'name': name, 'playlist': url,
                   'folder': validate_folder(folder), 'updated_at': time.time_ns()}
        self.data['libraries'].append(library)
        self.save()
        return copy.deepcopy(library)

    def update(self, library_id, name=None, playlist=None, folder=None):
        before = self.get(library_id)
        after = copy.deepcopy(before)
        if name is not None:
            name = str(name).strip()
            if not 1 <= len(name) <= 80:
                raise ValueError('Give this library a name between 1 and 80 characters.')
            after['name'] = name
        if playlist is not None:
            after['playlist'] = playlist_url(playlist)
            if any(x['id'] != library_id and x['playlist'] == after['playlist'] for x in self.data['libraries']):
                raise ValueError('That playlist is already saved in another library.')
        if folder is not None:
            after['folder'] = validate_folder(folder)
        if after != before:
            after['updated_at'] = time.time_ns()
            index = next(i for i,x in enumerate(self.data['libraries']) if x['id'] == library_id)
            self.data['libraries'][index] = after
            self.save()
        return after


def folder_picker_binary():
    source = Path(__file__).parent/'native/FolderPicker.swift'
    bundled = Path(__file__).resolve().parents[1]/'bin/FolderPicker'
    if bundled.is_file():
        return bundled
    app = Path(__file__).resolve().parents[1]/'.runtime'/'Pocket Sync Folder Picker.app'
    contents = app/'Contents'
    executable = contents/'MacOS/FolderPicker'
    if executable.exists() and executable.stat().st_mtime >= source.stat().st_mtime:
        return executable
    compiler = shutil.which('swiftc')
    if not compiler:
        raise ValueError('The native folder picker needs the Mac developer tools. Use Enter path manually for now.')
    executable.parent.mkdir(parents=True, exist_ok=True)
    (contents/'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'local.pocketsync.folderpicker', 'CFBundleName': 'Pocket Sync Folder Picker',
        'CFBundleDisplayName': 'Pocket Sync Folder Picker', 'CFBundleExecutable': 'FolderPicker',
        'CFBundlePackageType': 'APPL', 'NSHighResolutionCapable': True,
    }))
    cache = app.parent/'swift-module-cache'
    cache.mkdir(exist_ok=True)
    compiled = subprocess.run([compiler, str(source), '-o', str(executable), '-module-cache-path', str(cache)],
                              capture_output=True, text=True, timeout=120)
    if compiled.returncode:
        raise ValueError('The folder picker could not be prepared. Use Enter path manually for now.')
    return executable


def choose_folder(initial=''):
    if sys.platform != 'darwin':
        raise ValueError('The native folder chooser is available on macOS. Use Enter path on this computer.')
    initial = Path(initial).expanduser() if initial else Path.home()
    if not initial.is_dir():
        initial = Path.home()
    try:
        result = subprocess.run([str(folder_picker_binary()), str(initial)], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as error:
        raise ValueError('The folder chooser timed out. Try again or use Enter path.') from error
    if result.returncode:
        raise ValueError('macOS could not open the folder chooser. Try again or use Enter path.')
    try:
        path = json.loads(result.stdout)['path']
    except (ValueError, KeyError) as error:
        raise ValueError('The folder chooser did not return a folder. Try again or use Enter path.') from error
    return validate_folder(path) if path else None
