# Slice 0A context-construction golden baseline (evidence for LD-04 §11.4)

**Status:** evidence record, 2026-10-11. Produced by running the **actual Slice 0A code at commit `01e9f46559cfca4c30777b940a8ca7d5f8af25d8`** (extracted read-only with `git archive`) through its own store, coordinator and context builder. It is not a reimplementation. No application code, schema or test in the repository was changed to produce it.

**Fixture file:** [ld-04-slice-0a-context-golden.json](ld-04-slice-0a-context-golden.json) — 7 fixtures, 17,191 bytes.
**sha256 of the file bytes:** `afb16c8821f80c5ce4eaf6aee328fb772ee7057e6b62c8d810fdab3e5e2d5bf1`
**sha256 of its canonical serialization** (`json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True)`): `83c4a51f9643a977c8391675967b1a1434567f1e574882e065fe27d9b64d4553`

## What Slice 0A actually applied to a model request

From source at `01e9f46` and from the captured types (`facts` in the fixture file):

- `ModelRequest` has exactly one field, `messages`; `ContextMessage` has exactly `role` and `content`. There is no field for system instructions, sampling or other settings, a budget, omission evidence, or a behavior profile.
- `ContextBuilder.build` returns every committed message of the conversation from position 1 through the triggering user message, in `position` order, role and content unchanged (no trimming, normalization, truncation, summarization or Memory).
- `ExecutionCoordinator.submit` passes that request to the model port unchanged; the only content check is the 32,000-character bound on a submitted user message.
- Failed runs contribute nothing (they have no assistant message); the user message of a failed run remains in later views.

So the **effective configuration of 0A** is: whole-history, roles and content verbatim, ordered by position, no system instructions, no parameters, no behavior profile. The fixtures pin this behavior. They do **not** capture, and the design must never claim, any 0A persona, model, runtime or version provenance (0A never recorded any, apart from `model_id`/`runtime_id` of the fake adapter), and they say nothing about the fake adapter's reply text, which is runtime behavior rather than configuration.

## Fixtures

| ID | Pins |
| --- | --- |
| FX-01 | single user message |
| FX-02 | three alternating turns; each dispatched view is the whole committed prefix |
| FX-03 | verbatim text: leading/trailing whitespace, CRLF, tabs, NFC vs NFD, emoji, RTL, a bracket marker; nothing trimmed or normalized |
| FX-04 | maximum-length (32,000 characters) user message; content stored as rule `'ab'*16000` plus its sha256 |
| FX-05 | a failed run: its user message stays, no assistant message for it |
| FX-06 | authoritative order is `position`, not commit instant (clock runs backwards) |
| FX-07 | two conversations interleaved in one database; no cross-conversation leakage |

Each fixture records the history, the request actually **received by the model port** at dispatch, and the views rebuilt by `ContextBuilder` over the final history (cut-off at the trigger), each with a sha256 of the canonical view.

## Capture procedure (reproducible)

1. `git archive 01e9f46 server/src | tar -x -C <empty dir>` — the reference implementation, untouched.
2. Run the script below with the repository virtualenv interpreter in isolated mode from a directory other than the extracted tree: `python -I capture_golden.py <empty dir>/server/src <out.json>`. It drives the real `migrate`, `SqliteStore`, `ExecutionCoordinator` and `ContextBuilder` with a scripted model stub that records the request it receives.
3. Run it twice; the outputs must be byte-identical (verified on 2026-10-11: identical).
4. Compare `sha256` of the output with the digests above. A different digest means the reference was not reproduced.

## Comparison procedure for the 0B-1 baseline

1. The 0B-1 test suite loads this fixture file (its sha256 pinned in the test and in the manifest of the baseline configuration `E0`), expands the `@rule:` marker, and replays each fixture history through the **0B-1** store and `E0` context builder.
2. For every fixture it compares, byte-for-byte on the canonical serialization, the constructed view with the recorded `view` (and `view_sha256`). Any difference fails the build.
3. The comparison runs (a) as a build/test gate and (b) as a cheap startup self-test of the shipped `E0` builder; failing (b) marks `E0` unavailable (design §11.4).
4. An independent reviewer can recompute steps 1–4 of the capture procedure from `01e9f46` without trusting the 0B-1 code.

## Limits

This pins the **constructed view only**. It does not establish continuity of model behavior, of the fake adapter's replies, of capacity refusal (0B refuses over-capacity input; 0A had no budget), or of any provenance. It is an evidence and compatibility requirement, not a persona or Memory feature.

## Appendix — capture script (documentation, not committed tooling)

```python
"""Capture the Slice 0A constructed-view golden fixtures by running the REAL 0A code
(extracted read-only from commit 01e9f46) through its real store, coordinator and context builder.
Usage: python -I capture_golden.py <extracted-src-root> <out.json>"""
import sys, json, hashlib, tempfile, dataclasses, uuid
from datetime import datetime, timedelta, UTC
from pathlib import Path

src, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, src)
from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.context import ContextBuilder
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import (ModelExecutionError, ModelIdentity, ModelOutput,
                                               ModelRequest, ContextMessage)
from anonymous.domain.ids import ConversationId, SubmissionId

IDENT = ModelIdentity("golden-stub-model", "golden-stub-runtime")

class Stub:
    """Scripted ModelPort: returns scripted text; records the exact request it receives."""
    def __init__(self): self.script=[]; self.requests=[]
    @property
    def identity(self): return IDENT
    def generate(self, request):
        self.requests.append(request)
        nxt = self.script.pop(0)
        if nxt is None: raise ModelExecutionError("stub_failure", "scripted failure")
        return ModelOutput(content=nxt, identity=IDENT)

class Clock:
    def __init__(self, instants): self.i=list(instants); self.n=0
    def now(self):
        v=self.i[min(self.n,len(self.i)-1)]; self.n+=1; return v

def canon(o): return json.dumps(o, sort_keys=True, separators=(",",":"), ensure_ascii=True)
def sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
BASE = datetime(2026,1,1,12,0,0,tzinfo=UTC)

def run_fixture(fid, description, turns, clock=None, extra=None):
    """turns: list of (user_text, assistant_text_or_None_for_failure)."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d)/"g.sqlite3"; migrate(db)
        store = SqliteStore(db, clock or Clock([BASE+timedelta(seconds=k) for k in range(10000)]))
        owner = store.ensure_dev_owner()
        stub = Stub(); coord = ExecutionCoordinator(store, ContextBuilder(store), stub)
        conv = store.create_conversation(owner, None)
        views=[]; 
        for u,a in turns:
            stub.script.append(a)
            n=len(stub.requests)
            coord.submit(owner=owner, conversation_id=conv.id, submission_id=SubmissionId(str(uuid.uuid4())), content=u)
            req=stub.requests[n]
            views.append([{"role":m.role.value,"content":m.content} for m in req.messages])
        hist=store.get_history(owner, conv.id)
        history=[{"position":m.position,"role":m.role.value,"content":m.content} for m in hist.messages]
        triggers=[m.position for m in hist.messages if m.role.value=="user"]
        rec={"id":fid,"description":description,"history_after":history,
             "dispatched_views":[{"trigger_position":p,"view":v,"view_sha256":sha(canon(v))} for p,v in zip(triggers,views)]}
        # re-derive every user trigger view with the real ContextBuilder over the FINAL history (cut-off check)
        cb=ContextBuilder(store); rebuilt=[]
        for m in hist.messages:
            if m.role.value=="user":
                v=[{"role":x.role.value,"content":x.content} for x in cb.build(m).messages]
                rebuilt.append({"trigger_position":m.position,"view":v,"view_sha256":sha(canon(v))})
        rec["rebuilt_views_over_final_history"]=rebuilt
        rec["runs"]=[{"status":r.status.value,"failure_code":r.failure_code} for r in hist.runs]
        if extra: rec.update(extra(store, owner))
        return rec

fx=[]
fx.append(run_fixture("FX-01","single user message, one successful turn",[("Hello",'Hi there')]))
fx.append(run_fixture("FX-02","three alternating turns; each dispatched view is the whole committed prefix through its trigger",
   [("First question","First answer"),("Second question","Second answer"),("Third question","Third answer")]))
fx.append(run_fixture("FX-03","text fidelity: whitespace, CRLF, tabs, NFC/NFD, emoji, RTL, bracket marker; no trimming/normalization",
   [("  leading and trailing  \n","  reply with spaces \r\n"),("line1\r\nline2\tTabbed","café"),("café vs café \U0001F600 שלום","[fake:fail] literal text in assistant content"),("[fake:fail] in user content with a scripted stub","ok")]))
big="ab"*16000
fx.append(run_fixture("FX-04","maximum-length user message (32000 characters, content_rule 'ab'*16000), no truncation",
   [(big,"short")], extra=lambda s,o:{"content_rule":"'ab' * 16000","big_user_content_sha256":sha(big)}))
fx.append(run_fixture("FX-05","failed attempt contributes nothing: user message whose run failed stays in later views; no assistant message for it",
   [("will fail",None),("after failure","recovered")]))
# order vs time: instants go backwards while positions go forwards
back=[BASE+timedelta(seconds=100-k) for k in range(100)]
fx.append(run_fixture("FX-06","authoritative order is position, not commit instant: clock runs backwards",
   [("one","uno"),("two","dos"),("three","tres")], clock=Clock(back)))

# isolation: second conversation in the same database never leaks into the first
with tempfile.TemporaryDirectory() as d:
    db=Path(d)/"g.sqlite3"; migrate(db)
    store=SqliteStore(db, Clock([BASE+timedelta(seconds=k) for k in range(10000)]))
    owner=store.ensure_dev_owner(); stub=Stub(); coord=ExecutionCoordinator(store, ContextBuilder(store), stub)
    c1=store.create_conversation(owner,None); c2=store.create_conversation(owner,None)
    for c,u,a in [(c1,"A1","a1"),(c2,"B1","b1"),(c1,"A2","a2"),(c2,"B2","b2")]:
        stub.script.append(a); n=len(stub.requests)
        coord.submit(owner=owner, conversation_id=c.id, submission_id=SubmissionId(str(uuid.uuid4())), content=u)
    views=[[{"role":m.role.value,"content":m.content} for m in r.messages] for r in stub.requests]
    fx.append({"id":"FX-07","description":"two conversations interleaved in one database; each dispatched view contains only its own conversation",
      "dispatched_views_in_call_order":[{"view":v,"view_sha256":sha(canon(v))} for v in views]})

facts={
 "reference_commit":"01e9f46559cfca4c30777b940a8ca7d5f8af25d8",
 "model_request_fields":[f.name for f in dataclasses.fields(ModelRequest)],
 "context_message_fields":[f.name for f in dataclasses.fields(ContextMessage)],
 "note":"The 0A ModelRequest carries only an ordered tuple of (role, content). 0A applied no system instructions, no sampling or other settings, no budget/omission and no behavior profile. These are properties of the 0A types captured here, not an assumption."}
def elide(o):
    if isinstance(o,dict): return {k:elide(v) for k,v in o.items()}
    if isinstance(o,list): return [elide(v) for v in o]
    if o==big: return "@rule:'ab'*16000"
    return o
doc=elide({"schema":"ld-04-slice-0a-context-golden/1","facts":facts,"fixtures":fx})
text=canon(doc)
Path(out).write_text(json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=True)+"\n", encoding="utf-8")
print("canonical_sha256", sha(text)); print("file_sha256", hashlib.sha256(Path(out).read_bytes()).hexdigest())
print("fixtures", len(fx), "bytes", Path(out).stat().st_size)
```
