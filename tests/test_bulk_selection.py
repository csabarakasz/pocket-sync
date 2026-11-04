from pathlib import Path
import shutil
import subprocess
import unittest


class BulkSelectionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed for browser selection logic')
    def test_selection_is_scoped_persistent_and_pruned(self):
        source=(Path(__file__).parents[1]/'playlist_sync/web/app.js').read_text()
        logic=source[source.index('// Selection belongs'):source.index('const escape =')]
        script='''const assert=require('node:assert/strict');
const saved=new Map();
const sessionStorage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)};
'''+logic+'''
const make=(folder='player',scan='round1')=>({library_id:'edu',settings:{folder},scan_id:scan,tracks:[{id:'a',status:'missing'},{id:'b',status:'missing'}]});
updateSelection(make());assert.deepEqual([...selectedTracks],['a','b']);
selectedTracks.delete('a');saveSelection();updateSelection(make());assert.deepEqual([...selectedTracks],['b']);
selectionKey='';updateSelection(make());assert.deepEqual([...selectedTracks],['b']);
selectedTracks.clear();saveSelection();updateSelection(make());assert.equal(selectedTracks.size,0);
updateSelection(make('another player'));assert.equal(selectedTracks.size,2);
updateSelection(make('another player','round2'));assert.equal(selectedTracks.size,2);
const completed=make('another player','round2');completed.tracks[0].status='present';updateSelection(completed);assert.deepEqual([...selectedTracks],['b']);
updateSelection({...make(),library_id:'ami'});assert.equal(selectedTracks.size,2);
'''
        subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
