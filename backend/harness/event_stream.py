"""Small text frames: bounded latency without a disk transaction per token."""
import asyncio

from .events import Event


async def coalesced_events(queue, *, interval=0.05, max_chars=4096):
    pending=None
    loop=asyncio.get_running_loop()
    while True:
        event=pending if pending is not None else await queue.get()
        pending=None
        if event is None:return
        if event.type!='text':
            yield event
            continue
        parts=[str(event.data.get('text') or '')];size=len(parts[0]);deadline=loop.time()+interval
        ended=False
        while size<max_chars and loop.time()<deadline:
            try:following=await asyncio.wait_for(queue.get(),max(0,deadline-loop.time()))
            except TimeoutError:break
            if following is None:
                ended=True
                break
            if following.type!='text' or following.thread_id!=event.thread_id or following.data.keys()!=event.data.keys():
                pending=following
                break
            text=str(following.data.get('text') or '');parts.append(text);size+=len(text)
        yield Event('text',event.thread_id,{**event.data,'text':''.join(parts)},at=event.at)
        if ended:return
