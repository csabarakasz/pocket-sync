"""Restore a player's original filenames before later additions (stop the app first)."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playlist_sync.engine import folder_identity,ensure_folder
from playlist_sync.ordering import restore,rewrite_references

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path);parser.add_argument('journal',type=Path)
    parser.add_argument('--runtime',type=Path,default=Path(__file__).resolve().parents[1]/'.runtime/playlist-sync')
    args=parser.parse_args();identity=folder_identity(args.folder)
    mapping=restore(args.folder,args.journal,lambda:ensure_folder(args.folder,identity))
    rewrite_references(args.runtime,args.folder,mapping)
    print(f'Restored {len(mapping)} filenames.')
