"""Before/after reproduction of the two 0B-1 review races (remediation record, findings 1 and 2).

Uses only API that exists both at the reviewed commit ``ecef413`` and after the remediation.

    git worktree add /tmp/anonymous-0b1-old ecef413
    cd server
    PYTHONPATH=/tmp/anonymous-0b1-old/server/src uv run python ../docs/evidence/ld-04-0b1-remediation-race-repro.py   # old
    uv run python ../docs/evidence/ld-04-0b1-remediation-race-repro.py                                              # new

Synthetic data only; the database is a temporary directory.
"""

import sys, threading, tempfile
from pathlib import Path

sys.path.insert(0, ".")
import anonymous
from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.composition import build_application
from anonymous.config import Settings
from anonymous.domain.ids import SubmissionId, new_uuid
from tests.conftest import FAST
from tests.doubles import Fault, FaultyExecutionStore

print("code under test:", anonymous.__file__)


def new_app(tmp):
    rt = ScriptedRuntime()
    app = build_application(
        Settings(db_path=Path(tmp) / "d" / "x.sqlite3"), runtime=rt, execution_settings=FAST
    )
    return app, rt


# ---- Finding 1: registration -> pause -> shutdown -> start ----
orig = threading.Thread.start
reached, release = threading.Event(), threading.Event()


def gated(self):
    if self.name.startswith("anonymous-run-"):
        reached.set()
        release.wait(10)
    orig(self)


threading.Thread.start = gated
with tempfile.TemporaryDirectory() as tmp:
    app, rt = new_app(tmp)
    cid = app.conversations.create_conversation(app.owner).id
    box = []
    t = threading.Thread(
        target=lambda: box.append(
            app.execution.begin_submit(
                owner=app.owner,
                conversation_id=cid,
                submission_id=SubmissionId(new_uuid()),
                content="q",
            )
        )
    )
    t.start()
    reached.wait(5)
    # a concurrent spawn/poll elsewhere (old code filtered unstarted threads here)
    done = app.shutdown(timeout_seconds=0.2)
    print(
        "F1 shutdown() while the worker is registered but unstarted ->",
        done,
        "| guard held:",
        app.guard.held,
    )
    release.set()
    t.join(5)
    try:
        box[0].wait(5)
    except Exception as e:
        print("   worker error", type(e).__name__)
    print(
        "   the worker started after shutdown() returned; the guard is now:",
        "RELEASED (defect)" if not app.guard.held else "still held (correct)",
    )
    app.shutdown(2)
threading.Thread.start = orig

# ---- Finding 2: reconcile between admission commit and worker registration ----
with tempfile.TemporaryDirectory() as tmp:
    rt = ScriptedRuntime()
    app, rt = new_app(tmp)
    faulty = FaultyExecutionStore(app.store)
    # rebuild coordinator over the faulty store to inject the window
    from tests.conftest import Services

    svc = Services(faulty, rt)
    cid = svc.conversations.create_conversation(app.owner).id
    seen = {}

    def window():
        th = threading.Thread(target=lambda: seen.setdefault("report", svc.coordinator.reconcile()))
        th.start()
        th.join(1.0)
        seen["finished_inside_window"] = not th.is_alive()
        seen["th"] = th

    faulty.script("admit_submission", Fault("after", hook=window))
    out = svc.coordinator.submit(
        owner=app.owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    seen["th"].join(5)
    rep = seen.get("report")
    print(
        "F2 reconcile ran to completion inside the admission window:",
        seen["finished_inside_window"],
        "| pending settled by reconcile:",
        getattr(rep, "pending_settled", "?"),
    )
    print(
        "   run status:",
        out.run.status.value,
        "code:",
        out.run.failure_code,
        "| assistant message:",
        out.assistant_message is not None,
    )
    app.shutdown(2)
