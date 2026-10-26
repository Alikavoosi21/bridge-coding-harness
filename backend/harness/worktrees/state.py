"""Durable revisions of observed copy contents, independent of task lifecycle."""
import time


def observe(store,task_id,manifest_hash):
    store.task(task_id)
    with store.db.write() as db:
        previous=db.execute('SELECT * FROM working_copies WHERE task_id=?',(task_id,)).fetchone()
        if previous and previous['manifest_hash']==manifest_hash:return dict(previous)
        revision=previous['revision']+1 if previous else 1
        now=time.time()
        db.execute('INSERT INTO working_copies(task_id,revision,manifest_hash,updated_at) VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET revision=excluded.revision,manifest_hash=excluded.manifest_hash,updated_at=excluded.updated_at',(task_id,revision,manifest_hash,now))
    return {'task_id':task_id,'revision':revision,'manifest_hash':manifest_hash,'updated_at':now}
