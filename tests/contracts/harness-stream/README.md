# Harness stream fixtures

These fixtures are the contract between the backend journal and the renderer
transport. They are plain data so both Python and Node tests can read the same
bytes.

| File | What it proves |
|---|---|
| `events.json` | One full journal: task state, Persian + emoji text deltas with code-point offsets, message finish, plan, approval, action with a stable `operation_id`, budget, lease, selection quality, file change, verification, repair, apply-file and recovery. |
| `partial-snapshot.json` | A reload at sequence 3 with a partial assistant message. The next delta must continue at offset 4, exactly once. |
| `sse.txt` | An SSE replay with keepalive comments, `event: harness` frames and the `[DONE]` marker. A frame may arrive split across chunks; the decoder must wait for its blank line. |

Rules encoded here:

- `sequence` is per task and strictly increasing; a gap is an error, never a
  silent jump.
- Text offsets are Unicode code points, matching Python `len()`. `سلام` is 4 and
  ` 🎉` starts at offset 9 even though it is 2 UTF-16 units.
- A `finish` chunk ends a transport segment. It does not close the task unless
  the last task state is `closed`, `failed` or `cancelled`.
- An action's `operation_id` is the durable identity. A run segment id is
  location, not identity.
- Auth is a header (`Authorization: Bearer ...`); no token or provider key may
  appear in a URL or in the renderer.
