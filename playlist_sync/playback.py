"""Stable, append-only playback order without renaming existing music."""
from pathlib import Path
import os

PLAYLIST = 'Pocket Sync - Play in order.m3u8'
AUDIO = {'.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav', '.aac', '.wma'}


def update_playlist(folder):
    """Retain known order, prune missing paths, append new paths deterministically.

    The initial order is filename order, not a claim about device firmware.
    Relative paths make the playlist portable to the player.
    """
    folder = Path(folder)
    path = folder/PLAYLIST
    existing = []
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            relative = Path(line)
            if line and not line.startswith('#') and not relative.is_absolute() and '..' not in relative.parts:
                existing.append(line)
    available = []
    for base, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(base)/d).is_symlink())
        for name in files:
            item = Path(base)/name
            if not name.startswith('.') and item.suffix.lower() in AUDIO and not item.is_symlink():
                relative = item.relative_to(folder).as_posix()
                if '\n' not in relative and '\r' not in relative and not relative.startswith('#'):
                    available.append(relative)
    allowed = set(available)
    ordered = list(dict.fromkeys(x for x in existing if x in allowed))
    seen = set(ordered)
    ordered.extend(x for x in sorted(available, key=str.casefold) if x not in seen)
    body = '#EXTM3U\n'+'\n'.join(ordered)+'\n'
    if not path.exists() or path.read_text(encoding='utf-8') != body:
        tmp = folder/'.pocketsync-playback.tmp'
        try:
            with tmp.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    return ordered
