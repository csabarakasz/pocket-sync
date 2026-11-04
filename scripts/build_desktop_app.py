"""Build a local Mac app or a relocatable GitHub release ZIP."""
import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = '3.14.7'
MACOS_MINIMUM = '14.0'


def compile_swift(source, output, cache):
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['swiftc', str(ROOT/'playlist_sync/native'/source), '-o', str(output),
                    '-target', f'{platform.machine()}-apple-macos{MACOS_MINIMUM}',
                    '-module-cache-path', str(cache)], check=True)


def build_app(app, work, release):
    contents = app/'Contents'
    resources = contents/'Resources'
    resources.mkdir(parents=True, exist_ok=True)
    iconset = work/'PocketSync.iconset'
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = '@2x' if scale == 2 else ''
            pixels = str(size*scale)
            subprocess.run(['sips', '-z', pixels, pixels, str(ROOT/'assets/pocket-sync-logo.png'),
                            '--out', str(iconset/f'icon_{size}x{size}{suffix}.png')],
                           check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(resources/'PocketSync.icns')], check=True)
    info = {
        'CFBundleIdentifier': 'local.pocketsync.release' if release else 'local.pocketsync.desktop',
        'CFBundleName': 'Pocket Sync', 'CFBundleDisplayName': 'Pocket Sync',
        'CFBundleExecutable': 'PocketSync', 'CFBundlePackageType': 'APPL',
        'CFBundleIconFile': 'PocketSync.icns', 'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1', 'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': MACOS_MINIMUM,
    }
    if release:
        bundle_runtime(resources, work)
    else:
        info['PocketSyncProjectPath'] = str(ROOT)
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    compile_swift('DesktopLauncher.swift', contents/'MacOS/PocketSync', work/'swift-module-cache')
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)


def bundle_runtime(resources, work):
    project = resources/'project'
    shutil.copytree(ROOT/'playlist_sync', project/'playlist_sync',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    (project/'scripts').mkdir()
    for filename in ('download.py', 'scripts/launch_pocket_sync.py'):
        shutil.copy2(ROOT/filename, project/filename)
    compile_swift('FolderPicker.swift', project/'bin/FolderPicker', work/'swift-module-cache')

    env = os.environ | {'UV_PYTHON_INSTALL_DIR': str(work/'managed-python')}
    subprocess.run(['uv', 'python', 'install', PYTHON_VERSION, '--no-bin'], env=env, check=True)
    executable = subprocess.check_output(['uv', 'python', 'find', '--managed-python', PYTHON_VERSION],
                                         env=env, text=True).strip()
    python = resources/'python'
    shutil.copytree(Path(executable).resolve().parents[1], python, symlinks=True)
    subprocess.run(['uv', 'pip', 'install', '--python', str(python/'bin/python3'),
                    '--break-system-packages', '-r', str(ROOT/'requirements.txt'),
                    '-c', str(ROOT/'requirements-lock.txt')], env=env, check=True)
    # All runtime entry points use python -m. Generated console scripts contain
    # absolute build paths, so leave them out of the relocatable bundle.
    for entry in (python/'bin').iterdir():
        if entry.name not in ('python', 'python3', 'python3.14'):
            entry.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', action='store_true', help='Create a GitHub release ZIP with bundled Python')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        parser.error('Build the Mac app on macOS.')
    if args.release and not shutil.which('uv'):
        parser.error('Install uv before building a release.')
    if args.release:
        output = ROOT/'dist'
        output.mkdir(exist_ok=True)
        archive = output/f'Pocket-Sync-macOS-{platform.machine()}.zip'
        with TemporaryDirectory(prefix='pocket-sync-build-', dir=output) as directory:
            work = Path(directory)
            contents = work/'archive'
            app = contents/'Pocket Sync.app'
            build_app(app, work, release=True)
            shutil.copy2(ROOT/'Start Here.txt', contents/'Start Here.txt')
            staged_archive = work/archive.name
            subprocess.run(['ditto', '-c', '-k', str(contents), str(staged_archive)], check=True)
            staged_archive.replace(archive)
        print(archive)
    else:
        runtime = ROOT/'.runtime'
        runtime.mkdir(exist_ok=True)
        app = runtime/'Pocket Sync.app'
        with TemporaryDirectory(prefix='desktop-build-', dir=runtime) as directory:
            work = Path(directory)
            staged = work/app.name
            build_app(staged, work, release=False)
            if app.exists():
                shutil.rmtree(app)
            staged.replace(app)
        print(app)


if __name__ == '__main__':
    main()
