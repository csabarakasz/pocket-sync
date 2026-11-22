"""Install a clean Desktop bundle, keeping a reversible backup in .runtime."""
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def copy_clean(source, destination):
    shutil.copyfile(source, destination)
    shutil.copymode(source, destination)
    return destination


def main():
    source = ROOT/'.runtime/Pocket Sync.app'
    desktop = Path.home()/'Desktop'
    target = desktop/'Pocket Sync.app'
    staged = desktop/f'.Pocket Sync-{uuid.uuid4().hex}.app'
    backup = ROOT/'.runtime'/f'desktop-before-update-{uuid.uuid4().hex}.app'
    # copyfile deliberately avoids inherited Finder custom-icon metadata.
    shutil.copytree(source, staged, copy_function=copy_clean)
    try:
        subprocess.run(['xattr', '-cr', str(staged)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(staged)], check=True)
        if target.exists():
            target.rename(backup)
        try:
            staged.rename(target)
        except BaseException:
            if backup.exists():
                backup.rename(target)
            raise
        subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-f', str(target)], check=True)
        print(f'Installed: {target}\nBackup: {backup}')
    finally:
        if staged.exists():
            shutil.rmtree(staged)


if __name__ == '__main__':
    main()
