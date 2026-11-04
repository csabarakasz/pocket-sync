"""Apply the spotDL 4.6.0 URL-redirect cancellation workaround, idempotently."""
from importlib.metadata import distribution
from pathlib import Path

path = Path(distribution('spotdl').locate_file('spotdl/web/routes.py'))
source = path.read_text()
old = '''        yield SSE.redirect("/downloads")
        signals.song_url = signals.search_term
        async for update in gen_download(signals):
            yield update
'''
new = '''        # Local workaround: navigation closes the SSE request. Keep the
        # download alive independently rather than cancelling it on redirect.
        signals.song_url = signals.search_term
        async def finish_download():
            async for _update in gen_download(signals):
                pass
        task = asyncio.create_task(finish_download())
        _local_download_tasks.add(task)
        task.add_done_callback(_local_download_tasks.discard)
        await asyncio.sleep(0)
        yield SSE.redirect("/downloads")
        return
'''
if new not in source:
    if old not in source:
        raise SystemExit('spotDL route changed; workaround needs review.')
    backup = path.with_suffix('.py.original')
    if not backup.exists():
        backup.write_text(source)
    source = source.replace('router = APIRouter()', 'router = APIRouter()\n_local_download_tasks = set()', 1)
    path.write_text(source.replace(old, new, 1))
    print('Applied spotDL URL redirect workaround.')
else:
    print('spotDL URL redirect workaround is already applied.')
