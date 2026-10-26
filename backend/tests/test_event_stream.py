import asyncio

import pytest

from harness.event_stream import coalesced_events
from harness.events import Event


async def test_burst_text_is_lossless_and_keeps_tool_boundaries():
    queue=asyncio.Queue()
    original=['سلام '+str(i)+' 🟢' for i in range(1000)]
    for text in original:queue.put_nowait(Event('text','thread',{'text':text}))
    tool=Event('tool_started','thread',{'tool':'write_file'})
    queue.put_nowait(tool);queue.put_nowait(Event('text','thread',{'text':'after'}));queue.put_nowait(None)
    events=[event async for event in coalesced_events(queue)]
    index=events.index(tool)
    assert ''.join(e.data['text'] for e in events[:index])==''.join(original)
    assert events[index+1].data['text']=='after'
    assert len(events)<15


async def test_quiet_stream_flushes_without_waiting_for_completion():
    queue=asyncio.Queue();queue.put_nowait(Event('text','thread',{'text':'first'}))
    stream=coalesced_events(queue,interval=0.01)
    assert (await asyncio.wait_for(anext(stream),timeout=0.5)).data['text']=='first'
    queue.put_nowait(None)
    with pytest.raises(StopAsyncIteration):await anext(stream)


async def test_other_threads_are_not_merged_and_cancellation_closes_reader():
    queue=asyncio.Queue()
    queue.put_nowait(Event('text','one',{'text':'a'}));queue.put_nowait(Event('text','two',{'text':'b'}));queue.put_nowait(None)
    assert [(e.thread_id,e.data['text']) async for e in coalesced_events(queue)]==[('one','a'),('two','b')]
    stream=coalesced_events(asyncio.Queue())
    reader=asyncio.create_task(anext(stream));reader.cancel()
    with pytest.raises(asyncio.CancelledError):await reader
