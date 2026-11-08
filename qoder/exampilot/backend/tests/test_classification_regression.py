"""Classification regression tests over the live API.

Covers the 14 acceptance scenarios: MOS upload, 概率论, 数据结构 new course,
English, mixed language, cross-domain KP extraction with page evidence,
filename-vs-content conflict, low-confidence pending, candidate persistence
(identical across refreshes, no fabricated scores/sources), suggested confirm,
manual correct, reclassify, post-reclassify retrieval with citations, and
existing demo data integrity.

Runs against the live backend like test_auth.py; skipped when unreachable.
All writes happen under a fresh identity created through the real API.
"""

from __future__ import annotations

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
FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLES_DIR = Path(__file__).parent.parent.parent / "samples"
COURSE_MATERIALS_DIR = SAMPLES_DIR / "course_materials"


def _backend_up() -> bool:
    try:
        return httpx.get(f"{BASE}/api/health", timeout=5).status_code == 200
    except Exception:  # noqa: BLE001 - unreachable backend means skip, not fail
        return False


pytestmark = pytest.mark.skipif(
    not (_backend_up() and Path(SOCK).exists()),
    reason="live backend or seekdb socket not reachable",
)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(path: str, token: str) -> httpx.Response:
    return httpx.get(f"{BASE}{path}", headers=_headers(token), timeout=60)


def _post(path: str, token: str, json: dict | None = None) -> httpx.Response:
    return httpx.post(f"{BASE}{path}", headers=_headers(token), json=json, timeout=60)


def _upload(token: str, sid: str, filename: str, content: bytes) -> dict:
    r = httpx.post(
        f"{BASE}/api/sessions/{sid}/documents",
        headers=_headers(token),
        files={"files": (filename, content, "application/octet-stream")},
        timeout=180,
    )
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["ok"], result
    return result


def _doc(token: str, sid: str, document_id: int) -> dict:
    docs = _get(f"/api/sessions/{sid}/documents", token=token).json()
    for d in docs:
        if d["id"] == document_id:
            return d
    raise AssertionError(f"document {document_id} not listed")


@pytest.fixture(scope="module")
def db():
    import pymysql

    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def workspace(db) -> dict:
    """One fresh identity; uploads all scenario materials in order."""
    r = httpx.post(f"{BASE}/api/sessions", json={"name": "cls-regression"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    sid = r.json()["session"]["id"]

    def upload(name: str, data: bytes) -> dict:
        return _upload(token, sid, name, data)

    mos = upload("03-MOS-dynamic.md", (FIXTURE_DIR / "upload_mos.md").read_bytes())
    ds = upload(
        "data_structures_notes.md",
        (COURSE_MATERIALS_DIR / "data_structures_notes_uat2.md").read_bytes(),
    )
    prob = upload(
        "probability_notes.md",
        (COURSE_MATERIALS_DIR / "probability_notes_uat2.md").read_bytes(),
    )
    english = upload(
        "dsp_lecture_english.md", (FIXTURE_DIR / "english_dsp.md").read_bytes()
    )
    mixed = upload("cmos_notes.md", (SAMPLES_DIR / "cmos_notes.md").read_bytes())
    ds_kp = upload("ds_kp.md", (FIXTURE_DIR / "ds_notes.md").read_bytes())
    conflict = upload(
        "probability_概率论复习笔记.md",
        (FIXTURE_DIR / "mos_content_conflict.md").read_bytes(),
    )
    weak = upload("misc_notes.md", (FIXTURE_DIR / "low_signal.md").read_bytes())

    def evidence(document_id: int) -> dict:
        with db.cursor() as cur:
            cur.execute(
                "SELECT classify_evidence FROM documents WHERE id=%s", (document_id,)
            )
            row = cur.fetchone()
        return json.loads(row[0] or "{}")

    return {
        "token": token,
        "session_id": sid,
        "mos": mos,
        "ds": ds,
        "prob": prob,
        "english": english,
        "mixed": mixed,
        "ds_kp": ds_kp,
        "conflict": conflict,
        "weak": weak,
        "evidence": evidence,
    }


class TestUploadClassification:
    """Scenarios 1-5: per-material classification on upload."""

    def test_mos_auto_classified(self, workspace):
        doc = workspace["mos"]
        assert doc["course"] == "数字集成电路"
        assert doc["classify_status"] == "auto"
        assert doc["course_candidates"]
        assert any(c["source"] == "lexicon" for c in doc["course_candidates"])

    def test_data_structures_proposed_as_new_course(self, workspace):
        doc = workspace["ds"]
        assert doc["course"] == "数据结构与算法"
        assert doc["classify_reason"] == "new_course"
        assert doc["classify_status"] in ("suggested", "pending")
        assert any(c["source"] == "heading" for c in doc["course_candidates"])

    def test_probability_auto_classified(self, workspace):
        doc = workspace["prob"]
        assert doc["course"] == "概率论"
        assert doc["classify_status"] == "auto"

    def test_english_dsp_classified(self, workspace):
        doc = workspace["english"]
        assert doc["course"] == "数字信号处理"
        assert doc["classify_status"] in ("auto", "suggested")

    def test_mixed_language_classified(self, workspace):
        doc = workspace["mixed"]
        assert doc["course"] == "数字集成电路"
        assert doc["classify_status"] == "auto"


class TestCrossDomainKps:
    """Scenario 6: generic structured-heading KPs with real page evidence."""

    def test_term_heading_kps_with_page_evidence(self, workspace):
        ev = workspace["evidence"](workspace["ds_kp"]["id"])
        kps = ev.get("knowledge_points") or []
        assert "链表" in kps, kps
        assert "栈与队列" in kps, kps
        for kp in kps:
            assert "第一章" not in kp and "第二章" not in kp
        kp_evidence = ev.get("kp_evidence") or {}
        for name, slides in kp_evidence.items():
            assert len(slides) >= 2, name
        assert kp_evidence["链表"]
        assert kp_evidence["栈与队列"]

    def test_no_fabricated_kps_for_lexicon_course_without_kp_sets(self, workspace):
        ev = workspace["evidence"](workspace["prob"]["id"])
        kps = ev.get("knowledge_points") or []
        # 概率论 has no curated KP lexicon; only term-like heading evidence may
        # produce KPs, and chapter patterns are excluded.
        for kp in kps:
            assert "第一章" not in kp and "第二章" not in kp and "第三章" not in kp


class TestFilenameConflict:
    """Scenario 7: filename points elsewhere, content wins with an explicit reason."""

    def test_content_beats_filename_with_reason(self, workspace):
        doc = workspace["conflict"]
        assert doc["filename"] == "probability_概率论复习笔记.md"
        assert doc["course"] == "数字集成电路"
        assert doc["classify_reason"] == "filename_conflict"
        ev = workspace["evidence"](doc["id"])
        assert "filename_conflict" in (ev.get("signals") or {})


class TestLowConfidencePending:
    """Scenario 8: weak signals stay pending and show candidates, no forced course."""

    def test_pending_with_candidates_no_fabricated_scores(self, workspace):
        doc = workspace["weak"]
        assert doc["classify_status"] == "pending"
        assert doc["classify_reason"] == "new_course"
        assert doc["course"] == "电路基础"  # heading-proposed candidate, not confirmed
        candidates = doc["course_candidates"]
        assert candidates
        for c in candidates:
            assert c["name"] == "电路基础"
            assert c["source"] == "heading"
            assert 0.0 < c["score"] <= 0.5, c  # weak evidence, no fabricated confidence


class TestCandidatePersistence:
    """Scenario 9: candidates persist identically across refreshes."""

    def test_candidates_identical_across_refreshes(self, workspace):
        sid, token = workspace["session_id"], workspace["token"]
        first = _get(f"/api/sessions/{sid}/documents", token=token).json()
        second = _get(f"/api/sessions/{sid}/documents", token=token).json()
        by_id_1 = {d["id"]: d for d in first}
        by_id_2 = {d["id"]: d for d in second}
        assert by_id_1.keys() == by_id_2.keys()
        for doc_id in by_id_1:
            assert (
                by_id_1[doc_id]["course_candidates"]
                == by_id_2[doc_id]["course_candidates"]
            )
            assert (
                by_id_1[doc_id]["chapter_candidates"]
                == by_id_2[doc_id]["chapter_candidates"]
            )

    def test_classifier_version_and_reason_persisted(self, workspace):
        ev = workspace["evidence"](workspace["prob"]["id"])
        assert ev.get("classifier_version") == "3.1"
        assert ev.get("reason") in (
            "ok",
            "new_course",
            "ambiguous",
            "filename_conflict",
            "no_signal",
        )
        assert ev.get("status") in ("auto", "suggested", "pending")

    def test_stored_rows_are_not_relabelled_fresh(self, workspace):
        # v3+ evidence rows keep their original sources; the legacy fallback
        # label is never attached to rows written by the current classifier.
        ev = workspace["evidence"](workspace["mos"]["id"])
        for c in ev.get("course_candidates") or []:
            assert c.get("source") != "stored_result"


class TestConfirmAndCorrect:
    """Scenarios 10-11: suggested confirm and manual correct end to end."""

    def test_suggested_confirm_links_course(self, workspace, db):
        token, sid = workspace["token"], workspace["session_id"]
        doc_id = workspace["ds"]["id"]
        r = _post(
            f"/api/documents/{doc_id}/confirm",
            token,
            json={
                "course": "数据结构与算法",
                "chapter": "线性表",
                "knowledge_points": ["链表", "栈"],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "confirmed"
        refreshed = _doc(token, sid, doc_id)
        assert refreshed["classify_status"] == "confirmed"
        assert refreshed["course"] == "数据结构与算法"
        assert "链表" in refreshed["knowledge_points"]
        courses = _get(f"/api/sessions/{sid}/courses", token=token).json()
        assert any(
            c["name"] == "数据结构与算法" and c["status"] == "confirmed"
            for c in courses
        )
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM classification_feedback WHERE document_id=%s",
                (doc_id,),
            )
            assert cur.fetchone()[0] >= 1

    def test_manual_correct_updates_classification(self, workspace, db):
        token, sid = workspace["token"], workspace["session_id"]
        doc_id = workspace["weak"]["id"]
        r = _post(
            f"/api/documents/{doc_id}/correct",
            token,
            json={"course": "电路基础", "chapter": None, "knowledge_points": []},
        )
        assert r.status_code == 200, r.text
        refreshed = _doc(token, sid, doc_id)
        assert refreshed["classify_status"] == "confirmed"
        assert refreshed["course"] == "电路基础"
        with db.cursor() as cur:
            cur.execute(
                "SELECT user_confirmed FROM classification_feedback WHERE document_id=%s "
                "ORDER BY id DESC LIMIT 1",
                (doc_id,),
            )
            assert (
                cur.fetchone()[0] == 0
            )  # manual correction, not a confirmed suggestion


class TestReclassify:
    """Scenarios 12-13: reclassify then retrieve with citations."""

    def test_reclassify_updates_evidence(self, workspace, db):
        token = workspace["token"]
        doc_id = workspace["prob"]["id"]
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM classification_feedback WHERE document_id=%s",
                (doc_id,),
            )
            feedback_before = cur.fetchone()[0]
        r = _post(f"/api/documents/{doc_id}/reclassify", token, json={})
        assert r.status_code == 200, r.text
        with db.cursor() as cur:
            cur.execute(
                "SELECT classify_evidence FROM documents WHERE id=%s", (doc_id,)
            )
            after = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM classification_feedback WHERE document_id=%s",
                (doc_id,),
            )
            feedback_after = cur.fetchone()[0]
        assert feedback_after == feedback_before + 1
        new_ev = json.loads(after)
        assert new_ev.get("classifier_version") == "3.1"
        assert new_ev.get("course") == "概率论"

    def test_post_reclassify_search_returns_citations(self, workspace):
        token, sid = workspace["token"], workspace["session_id"]
        doc_id = workspace["prob"]["id"]
        r = _post(
            f"/api/sessions/{sid}/search",
            token,
            json={"query": "随机变量", "limit": 10},
        )
        assert r.status_code == 200, r.text
        hits = r.json()["hits"]
        assert hits, "reclassified document must be retrievable"
        assert any(h["document_id"] == doc_id for h in hits)
        for h in hits:
            if h["document_id"] == doc_id:
                assert h.get("course") == "概率论"


class TestDemoDataIntact:
    """Scenario 14: pre-existing demo/legacy data is untouched by all of the above."""

    LEGACY_COUNTS: ClassVar[dict[str, tuple[int, int, int, int, int]]] = {
        # session_id: (documents, courses, questions, attempts, memory_events)
        "27a291634c6f4297": (4, 3, 0, 0, 3),
        "fd03b69768d343b2": (0, 0, 0, 0, 1),
        "9e7fc0f065134af5": (1, 1, 0, 0, 1),
        "0672a230825e4502": (1, 1, 25, 10, 5),
        "d181a2a90f614248": (2, 1, 25, 5, 3),
    }

    def test_legacy_session_counts_unchanged(self, db):
        with db.cursor() as cur:
            for sid, (
                docs,
                courses,
                questions,
                attempts,
                mems,
            ) in self.LEGACY_COUNTS.items():
                cur.execute(
                    "SELECT COUNT(*) FROM documents WHERE session_id=%s", (sid,)
                )
                assert cur.fetchone()[0] == docs, sid
                cur.execute("SELECT COUNT(*) FROM courses WHERE session_id=%s", (sid,))
                assert cur.fetchone()[0] == courses, sid
                cur.execute(
                    "SELECT COUNT(*) FROM questions WHERE session_id=%s", (sid,)
                )
                assert cur.fetchone()[0] == questions, sid
                cur.execute(
                    "SELECT COUNT(*) FROM attempts a JOIN practice_sessions ps "
                    "ON a.practice_session_id=ps.id WHERE ps.session_id=%s",
                    (sid,),
                )
                assert cur.fetchone()[0] == attempts, sid
                cur.execute(
                    "SELECT COUNT(*) FROM memory_events WHERE session_id=%s", (sid,)
                )
                assert cur.fetchone()[0] == mems, sid
