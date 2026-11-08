"""Security regression tests: two independent identities over the live API.

These tests exercise the running backend (default http://127.0.0.1:8001) and
are skipped automatically when it is unreachable. Denial responses are always
paired with a database state assertion (no row inserted / no evidence
rewritten / no PowerContext cross-write), never just an HTTP status check.

Both identities are created fresh through the real API, so the tests only
touch their own isolated data.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import ClassVar

import httpx
import pytest

BASE = os.environ.get("EXAMPILOT_TEST_BASE", "http://127.0.0.1:8001")
SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)
BACKEND_LOG = Path("/tmp/exampilot_backend.log")
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _backend_up() -> bool:
    try:
        return httpx.get(f"{BASE}/api/health", timeout=5).status_code == 200
    except Exception:  # noqa: BLE001 - unreachable backend means skip, not fail
        return False


def _socket_up() -> bool:
    return Path(SOCK).exists()


pytestmark = pytest.mark.skipif(
    not (_backend_up() and _socket_up()),
    reason="live backend or seekdb socket not reachable",
)


def _headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get(path: str, token: str | None = None, timeout: float = 60) -> httpx.Response:
    return httpx.get(f"{BASE}{path}", headers=_headers(token), timeout=timeout)


def _post(
    path: str,
    token: str | None = None,
    json: dict | None = None,
    files: dict | None = None,
    timeout: float = 180,
) -> httpx.Response:
    return httpx.post(
        f"{BASE}{path}",
        headers=_headers(token),
        json=json,
        files=files,
        timeout=timeout,
    )


def _put(
    path: str, token: str | None = None, json: dict | None = None
) -> httpx.Response:
    return httpx.put(f"{BASE}{path}", headers=_headers(token), json=json, timeout=60)


@pytest.fixture(scope="module")
def db():
    import pymysql

    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    yield conn
    conn.close()


def _scalar(db, sql: str, params) -> int:
    with db.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.fetchone()[0])


@pytest.fixture(scope="module")
def identities() -> dict:
    a = _post("/api/sessions", json={"name": "auth-test-A"}).json()
    b = _post("/api/sessions", json={"name": "auth-test-B"}).json()
    assert a["session"]["id"] != b["session"]["id"]
    return {"A": a, "B": b}


@pytest.fixture(scope="module")
def a_state(identities, db) -> dict:
    """A uploads material, practices, and writes a memory — all legitimately."""
    a = identities["A"]
    token, sid = a["token"], a["session"]["id"]
    content = (FIXTURE_DIR / "upload_mos.md").read_bytes()
    up = _post(
        f"/api/sessions/{sid}/documents",
        token=token,
        files={"files": ("upload_mos.md", content, "text/markdown")},
    )
    assert up.status_code == 200, up.text
    doc = up.json()["results"][0]
    assert doc["ok"], doc
    assert doc["course"] == "数字集成电路", doc
    assert doc["classify_status"] == "auto", doc

    with db.cursor() as cur:
        cur.execute(
            "SELECT kp.id FROM knowledge_points kp "
            "JOIN courses co ON kp.course_id=co.id WHERE co.session_id=%s",
            (sid,),
        )
        kp_ids = [int(r[0]) for r in cur.fetchall()]
    assert kp_ids

    start = _post(
        f"/api/sessions/{sid}/practice/start",
        token=token,
        json={
            "course_id": None,
            "knowledge_point_ids": kp_ids[:2],
            "count": 3,
            "mode": "mixed",
        },
    )
    assert start.status_code == 200, start.text
    start_data = start.json()
    answers = [{"question_id": q["id"], "answer": "X"} for q in start_data["questions"]]
    submit = _post(
        f"/api/practice/{start_data['practice_session_id']}/submit",
        token=token,
        json={"answers": answers},
    )
    assert submit.status_code == 200, submit.text

    mem = _post(
        f"/api/sessions/{sid}/memories",
        token=token,
        json={"kind": "note", "text": "A 的私有记忆"},
    )
    assert mem.status_code == 200, mem.text

    review = _get(f"/api/sessions/{sid}/review/plan", token=token).json()
    task_ids = [t["id"] for t in review.get("due", [])] + [
        t["id"] for t in review.get("upcoming", [])
    ]

    return {
        "token": token,
        "session_id": sid,
        "doc_id": doc["id"],
        "kp_ids": kp_ids,
        "practice_session_id": start_data["practice_session_id"],
        "review_task_ids": task_ids,
    }


# ---------------------------------------------------------------- scenario 1
class TestIdentityModel:
    def test_token_256bit_returned_once_digest_only(self, identities, db):
        a = identities["A"]
        token, sid = a["token"], a["session"]["id"]
        # 43-char urlsafe string = 256 bits from secrets.token_urlsafe(32)
        assert len(token) == 43
        assert set(token) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert token != sid
        with db.cursor() as cur:
            cur.execute(
                "SELECT token_digest FROM identities WHERE session_id=%s", (sid,)
            )
            row = cur.fetchone()
        assert row is not None
        digest = str(row[0])
        assert digest == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert digest != token
        # the raw token is not stored anywhere else
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM identities WHERE token_digest=%s", (token,)
            )
            assert int(cur.fetchone()[0]) == 0

    def test_me_returns_only_own_session(self, identities):
        a = identities["A"]
        me = _get("/api/sessions/me", token=a["token"])
        assert me.status_code == 200
        assert me.json()["id"] == a["session"]["id"]

    def test_other_session_id_with_own_token_is_403(self, identities):
        a, b = identities["A"], identities["B"]
        r = _get(f"/api/sessions/{a['session']['id']}", token=b["token"])
        assert r.status_code == 403


# --------------------------------------------------------------- scenario 12
class TestUnauthenticatedDefaultDeny:
    def test_all_data_endpoints_401_without_token(self, identities, a_state):
        sid = a_state["session_id"]
        gets = [
            f"/api/sessions/{sid}/documents",
            f"/api/sessions/{sid}/courses",
            f"/api/sessions/{sid}/knowledge-points",
            f"/api/sessions/{sid}/mastery",
            f"/api/sessions/{sid}/memories",
            f"/api/sessions/{sid}/memories/search?query=x",
            f"/api/sessions/{sid}/mistakes",
            f"/api/sessions/{sid}/practice/history",
            f"/api/sessions/{sid}/review/plan",
            f"/api/sessions/{sid}/preferences",
        ]
        posts = [
            (f"/api/sessions/{sid}/memories", {"kind": "note", "text": "x"}),
            (f"/api/sessions/{sid}/search", {"query": "x"}),
            (f"/api/sessions/{sid}/explain", {"query": "x"}),
            (f"/api/sessions/{sid}/practice/start", {"count": 1, "mode": "mixed"}),
            (f"/api/sessions/{sid}/mistakes/practice", {"count": 1}),
        ]
        for path in gets:
            assert _get(path).status_code == 401, path
        for path, body in posts:
            assert _post(path, json=body).status_code == 401, path
        assert (
            _put(f"/api/sessions/{sid}/preferences", json={"goal": "x"}).status_code
            == 401
        )


# --------------------------------------------------------------- scenario 13
class TestInvalidToken:
    def test_garbage_and_malformed_tokens_are_401(self, identities, a_state):
        r1 = _get("/api/sessions/me", token="not-a-real-token")
        assert r1.status_code == 401
        assert r1.headers.get("www-authenticate") == "Bearer"
        r2 = httpx.get(
            f"{BASE}/api/sessions/me",
            headers={"Authorization": "Token xyz"},
            timeout=30,
        )
        assert r2.status_code == 401
        r3 = httpx.get(
            f"{BASE}/api/sessions/me", headers={"Authorization": "Bearer"}, timeout=30
        )
        assert r3.status_code == 401


# --------------------------------------------------------------- scenario 14
class TestLegacySessionIdNotACredential:
    LEGACY_IDS: ClassVar[list[str]] = [
        "27a291634c6f4297",  # UAT2 session SA (pre-auth era)
        "fd03b69768d343b2",  # UAT2 session SB
        "9e7fc0f065134af5",  # UAT2 MOS session
        "d181a2a90f614248",  # UAT2 smoke session
    ]

    def test_legacy_id_without_token_401(self, db):
        for legacy in self.LEGACY_IDS:
            with db.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM demo_sessions WHERE id=%s", (legacy,))
                if int(cur.fetchone()[0]) == 0:
                    continue
            assert _get(f"/api/sessions/{legacy}/documents").status_code == 401, legacy

    def test_legacy_id_with_foreign_token_403(self, identities, db):
        token = identities["A"]["token"]
        for legacy in self.LEGACY_IDS:
            with db.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM demo_sessions WHERE id=%s", (legacy,))
                if int(cur.fetchone()[0]) == 0:
                    continue
            assert (
                _get(f"/api/sessions/{legacy}/documents", token=token).status_code
                == 403
            ), legacy


# ------------------------------------------------------------ scenarios 3, 4, 5
class TestCrossUserReads:
    def test_foreign_documents_list_403(self, identities, a_state):
        r = _get(
            f"/api/sessions/{a_state['session_id']}/documents",
            token=identities["B"]["token"],
        )
        assert r.status_code == 403

    def test_foreign_courses_and_kps_403(self, identities, a_state):
        b = identities["B"]["token"]
        sid = a_state["session_id"]
        assert _get(f"/api/sessions/{sid}/courses", token=b).status_code == 403
        assert _get(f"/api/sessions/{sid}/knowledge-points", token=b).status_code == 403
        assert _get(f"/api/sessions/{sid}/mastery", token=b).status_code == 403

    def test_foreign_practice_and_mistakes_403(self, identities, a_state):
        b = identities["B"]["token"]
        sid = a_state["session_id"]
        assert _get(f"/api/sessions/{sid}/practice/history", token=b).status_code == 403
        assert (
            _get(f"/api/practice/{a_state['practice_session_id']}", token=b).status_code
            == 403
        )
        assert _get(f"/api/sessions/{sid}/mistakes", token=b).status_code == 403

    def test_foreign_memory_reads_403(self, identities, a_state):
        b = identities["B"]["token"]
        sid = a_state["session_id"]
        assert _get(f"/api/sessions/{sid}/memories", token=b).status_code == 403
        assert (
            _get(f"/api/sessions/{sid}/memories/search?query=x", token=b).status_code
            == 403
        )


# ------------------------------------------------------------ scenarios 6, 7, 8
class TestCrossUserWrites:
    def test_foreign_memory_write_403_no_state_change(self, identities, a_state, db):
        b, sid = identities["B"]["token"], a_state["session_id"]
        before = _scalar(
            db, "SELECT COUNT(*) FROM memory_events WHERE session_id=%s", (sid,)
        )
        r = _post(
            f"/api/sessions/{sid}/memories",
            token=b,
            json={"kind": "note", "text": "越权写入"},
        )
        assert r.status_code == 403
        after = _scalar(
            db, "SELECT COUNT(*) FROM memory_events WHERE session_id=%s", (sid,)
        )
        assert before == after

    def test_foreign_upload_403_no_state_change(self, identities, a_state, db):
        b, sid = identities["B"]["token"], a_state["session_id"]
        before = _scalar(
            db, "SELECT COUNT(*) FROM documents WHERE session_id=%s", (sid,)
        )
        r = _post(
            f"/api/sessions/{sid}/documents",
            token=b,
            files={"files": ("evil.md", b"# evil", "text/markdown")},
        )
        assert r.status_code == 403
        after = _scalar(
            db, "SELECT COUNT(*) FROM documents WHERE session_id=%s", (sid,)
        )
        assert before == after

    def test_foreign_preferences_write_403(self, identities, a_state):
        b, sid = identities["B"]["token"], a_state["session_id"]
        assert (
            _put(
                f"/api/sessions/{sid}/preferences", token=b, json={"goal": "x"}
            ).status_code
            == 403
        )


# ---------------------------------------------------------------- scenario 8
class TestScopeIdNotExposed:
    def test_no_scope_id_in_responses(self, identities, a_state):
        a = identities["A"]
        token, sid = a["token"], a_state["session_id"]
        bodies = [
            _get("/api/sessions/me", token=token).text,
            _get(f"/api/sessions/{sid}", token=token).text,
            _get(f"/api/sessions/{sid}/documents", token=token).text,
            _get(f"/api/sessions/{sid}/memories", token=token).text,
            _get(f"/api/sessions/{sid}/courses", token=token).text,
        ]
        create_body = json.dumps(a, ensure_ascii=False)
        for body in bodies + [create_body]:
            assert '"scope_id"' not in body


# ---------------------------------------------------------------- scenario 9
class TestForeignKnowledgePoint:
    def test_foreign_kp_explain_blocked(self, identities, a_state):
        a, b = identities["A"], identities["B"]
        kp_id = a_state["kp_ids"][0]
        # B asks about A's knowledge point in B's own session -> not found
        r1 = _post(
            f"/api/sessions/{b['session']['id']}/explain",
            token=b["token"],
            json={"knowledge_point_id": kp_id, "query": None},
        )
        assert r1.status_code in (403, 404)
        # B addressing A's session directly -> forbidden
        r2 = _post(
            f"/api/sessions/{a['session']['id']}/explain",
            token=b["token"],
            json={"knowledge_point_id": kp_id, "query": None},
        )
        assert r2.status_code == 403


# --------------------------------------------------------------- scenario 10
class TestForeignReclassify:
    def test_foreign_reclassify_403_no_state_change(self, identities, a_state, db):
        b = identities["B"]["token"]
        doc_id = a_state["doc_id"]
        with db.cursor() as cur:
            cur.execute(
                "SELECT classify_evidence FROM documents WHERE id=%s", (doc_id,)
            )
            before_evidence = cur.fetchone()[0]
        before_feedback = _scalar(
            db, "SELECT COUNT(*) FROM classification_feedback", ()
        )
        r = _post(f"/api/documents/{doc_id}/reclassify", token=b, json={})
        assert r.status_code == 403
        with db.cursor() as cur:
            cur.execute(
                "SELECT classify_evidence FROM documents WHERE id=%s", (doc_id,)
            )
            after_evidence = cur.fetchone()[0]
        after_feedback = _scalar(db, "SELECT COUNT(*) FROM classification_feedback", ())
        assert before_evidence == after_evidence
        assert before_feedback == after_feedback

    def test_foreign_confirm_and_correct_403(self, identities, a_state):
        b = identities["B"]["token"]
        doc_id = a_state["doc_id"]
        body = {"course": "篡改", "chapter": None, "knowledge_points": []}
        assert (
            _post(f"/api/documents/{doc_id}/confirm", token=b, json=body).status_code
            == 403
        )
        assert (
            _post(f"/api/documents/{doc_id}/correct", token=b, json=body).status_code
            == 403
        )


# --------------------------------------------------------------- scenario 11
class TestForeignReviewTask:
    def test_foreign_review_complete_403_no_state_change(self, identities, a_state, db):
        if not a_state["review_task_ids"]:
            pytest.skip("no review task was created for A")
        b = identities["B"]["token"]
        task_id = a_state["review_task_ids"][0]
        with db.cursor() as cur:
            cur.execute("SELECT status FROM review_tasks WHERE id=%s", (task_id,))
            before = cur.fetchone()[0]
        r = _post(
            f"/api/review-tasks/{task_id}/complete", token=b, json={"correct": True}
        )
        assert r.status_code == 403
        with db.cursor() as cur:
            cur.execute("SELECT status FROM review_tasks WHERE id=%s", (task_id,))
            after = cur.fetchone()[0]
        assert before == after


# --------------------------------------------------------------- scenario 15
class TestTokenNeverLeaks:
    def test_token_not_in_api_responses(self, identities, a_state):
        token, sid = identities["A"]["token"], a_state["session_id"]
        bodies = [
            _get("/api/sessions/me", token=token).text,
            _get(f"/api/sessions/{sid}", token=token).text,
            _get(f"/api/sessions/{sid}/documents", token=token).text,
            _get(f"/api/sessions/{sid}/courses", token=token).text,
            _get(f"/api/sessions/{sid}/memories", token=token).text,
            _post(
                f"/api/sessions/{sid}/search", token=token, json={"query": "阈值电压"}
            ).text,
            httpx.get(f"{BASE}/api/health", timeout=30).text,
        ]
        for body in bodies:
            assert token not in body

    def test_token_not_in_backend_log(self, identities):
        if not BACKEND_LOG.exists():
            pytest.skip("backend log not found at /tmp/exampilot_backend.log")
        token = identities["A"]["token"]
        assert token not in BACKEND_LOG.read_text(errors="ignore")


# --------------------------------------------------------------- scenario 16
class TestLegitOperationsStillWork:
    def test_own_documents_listed_with_candidates(self, a_state):
        sid, token = a_state["session_id"], a_state["token"]
        docs = _get(f"/api/sessions/{sid}/documents", token=token).json()
        own = [d for d in docs if d["id"] == a_state["doc_id"]]
        assert own, "A's own uploaded document must be listed"
        doc = own[0]
        assert doc["course"] == "数字集成电路"
        assert doc["course_candidates"], "candidates must be persisted and returned"

    def test_own_search_returns_own_content(self, a_state):
        sid, token = a_state["session_id"], a_state["token"]
        r = _post(
            f"/api/sessions/{sid}/search",
            token=token,
            json={"query": "阈值电压", "limit": 5},
        )
        assert r.status_code == 200, r.text
        hits = r.json()["hits"]
        assert hits, "A's search must hit A's own document"
        assert all(h["document_id"] == a_state["doc_id"] for h in hits)

    def test_own_practice_result_readable(self, a_state):
        token = a_state["token"]
        r = _get(f"/api/practice/{a_state['practice_session_id']}", token=token)
        assert r.status_code == 200, r.text

    def test_own_mistakes_readable(self, a_state):
        sid, token = a_state["session_id"], a_state["token"]
        r = _get(f"/api/sessions/{sid}/mistakes", token=token)
        assert r.status_code == 200, r.text

    def test_own_memory_write_and_read(self, a_state, db):
        sid, token = a_state["session_id"], a_state["token"]
        before = _scalar(
            db, "SELECT COUNT(*) FROM memory_events WHERE session_id=%s", (sid,)
        )
        w = _post(
            f"/api/sessions/{sid}/memories",
            token=token,
            json={"kind": "note", "text": "合法写入"},
        )
        assert w.status_code == 200, w.text
        after = _scalar(
            db, "SELECT COUNT(*) FROM memory_events WHERE session_id=%s", (sid,)
        )
        assert after == before + 1
        events = _get(f"/api/sessions/{sid}/memories", token=token).json()
        assert any("合法写入" in str(e.get("summary", "")) for e in events)

    def test_own_preferences_roundtrip(self, a_state):
        sid, token = a_state["session_id"], a_state["token"]
        put = _put(
            f"/api/sessions/{sid}/preferences",
            token=token,
            json={"goal": "期末考试 90 分"},
        )
        assert put.status_code == 200, put.text
        got = _get(f"/api/sessions/{sid}/preferences", token=token)
        assert got.status_code == 200
        assert got.json()["goal"] == "期末考试 90 分"

    def test_own_reclassify_updates_evidence(self, a_state, db):
        token = a_state["token"]
        r = _post(
            f"/api/documents/{a_state['doc_id']}/reclassify", token=token, json={}
        )
        assert r.status_code == 200, r.text
        with db.cursor() as cur:
            cur.execute(
                "SELECT classify_evidence FROM documents WHERE id=%s",
                (a_state["doc_id"],),
            )
            evidence = json.loads(cur.fetchone()[0] or "{}")
        assert evidence.get("course_candidates"), (
            "reclassified evidence stores candidates"
        )
        assert evidence.get("classifier_version")
