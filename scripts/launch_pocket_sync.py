"""Start or reuse the loopback server for the Mac desktop app."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]


def healthy(port):
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            data = json.load(response)
        return data.get('app') == 'pocket-sync' and data.get('ok') is True
    except (OSError, ValueError):
        return False


def prepare_audio_tools(env, log):
    """Install missing tools with the same installers used by spotDL."""
    from spotdl.utils.config import get_spotdl_path

    tools = get_spotdl_path()
    env['PATH'] = str(tools) + os.pathsep + env['PATH']
    for name, flag in [('ffmpeg', '-version'), ('deno', '--version')]:
        executable = shutil.which(name, path=env['PATH'])
        if executable:
            try:
                if subprocess.run([executable, flag], env=env, stdout=log, stderr=log, timeout=10).returncode == 0:
                    continue
            except (OSError, subprocess.TimeoutExpired):
                pass
        subprocess.run([sys.executable, '-B', '-c', f'from spotdl.utils.{name} import download_{name}; download_{name}()'],
                       cwd=ROOT, env=env, stdout=log, stderr=log, check=True, timeout=180)
        subprocess.run([str(tools/name), flag], env=env, stdout=log, stderr=log, check=True, timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--packaged', action='store_true')
    args = parser.parse_args()
    port = 8879 if args.packaged else 8878
    runtime = (Path.home()/'Library/Application Support/Pocket Sync' if args.packaged
               else ROOT/'.runtime'/'playlist-sync')
    if healthy(port):
        return 0
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime/'desktop-launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if healthy(port):
            return 0
        env = os.environ.copy()
        env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:'+env.get('PATH','')
        if args.packaged:
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env.pop('PYTHONHOME', None)
            env.pop('PYTHONPATH', None)
        logpath = runtime/'desktop-launcher.log'
        with logpath.open('ab') as log:
            if args.packaged:
                try:
                    prepare_audio_tools(env, log)
                except (OSError, subprocess.SubprocessError):
                    print(f'Audio tool setup failed. Check your internet connection, then reopen Pocket Sync. Details: {logpath}',
                          file=sys.stderr)
                    return 1
            process = subprocess.Popen(
                [sys.executable, '-m', 'playlist_sync.server', '--no-browser', '--port', str(port), '--runtime', str(runtime)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True
            )
        for _ in range(100):
            if healthy(port):
                return 0
            if process.poll() is not None:
                break
            time.sleep(.15)
        if process.poll() is None:
            process.terminate()
        print(f'Pocket Sync could not start. Details are saved in {logpath}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
