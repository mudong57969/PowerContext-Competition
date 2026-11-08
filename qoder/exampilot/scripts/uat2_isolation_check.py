"""UAT2: cross-user data isolation probes (all calls are real API requests)."""

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8001"
SA = "27a291634c6f4297"  # UAT2-测试会话A (owns docs + memory)
SB = "fd03b69768d343b2"  # UAT2-隔离探针B (fresh anonymous "user")
MOS_SESS = "9e7fc0f065134af5"  # pre-existing session from round 1


def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + urllib.parse.quote(path, safe="/?=&"), data=data, method=method
    )
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:  # noqa: BLE001 - non-JSON error bodies degrade to {}
            return exc.code, {}


def main() -> None:
    print("== 0. seed: write one memory into SA (its own scope) ==")
    st, body = req(
        "POST",
        f"/api/sessions/{SA}/memories",
        {
            "kind": "note",
            "text": "UAT2 隔离测试：会话A的私有学习记忆内容-圆周率π≈3.14159",
        },
    )
    print(st, body)

    print("\n== 1. anonymous session enumeration (no auth) ==")
    st, body = req("GET", "/api/sessions")
    print("HTTP", st, "| sessions returned:", len(body))
    for s in body[:5]:
        print(
            f"  id={s['id']} name={s['name']} scope_id={s['scope_id']} docs={s['stats']['documents']}"
        )

    print("\n== 2. fresh anonymous session SB sees its own data (expect empty) ==")
    st, body = req("GET", f"/api/sessions/{SB}/documents")
    print("SB documents:", st, len(body))
    st, body = req("GET", f"/api/sessions/{SB}/memories")
    print("SB memories:", st, len(body))
    st, body = req("GET", f"/api/sessions/{SB}/memories/search?query=圆周率&limit=5")
    print("SB memory search:", st, json.dumps(body, ensure_ascii=False)[:200])
    st, body = req("GET", f"/api/sessions/{SB}/mastery")
    print("SB mastery:", st, len(body))

    print("\n== 3. SB reads OLD user SA's learning data (should be blocked, is it?) ==")
    st, body = req("GET", f"/api/sessions/{SA}/memories")
    print("SB -> SA memories:", st, json.dumps(body, ensure_ascii=False)[:300])
    st, body = req("GET", f"/api/sessions/{SA}/memories/search?query=圆周率&limit=5")
    print("SB -> SA memory search:", st, json.dumps(body, ensure_ascii=False)[:400])
    st, body = req("GET", f"/api/sessions/{SA}/documents")
    print("SB -> SA documents:", st, [(d["filename"], d["course"]) for d in body])

    print("\n== 4. SB reads round-1 user session (MOS) data ==")
    st, body = req("GET", f"/api/sessions/{MOS_SESS}/documents")
    print("SB -> MOS documents:", st, [(d["filename"], d["course"]) for d in body])
    st, body = req("GET", f"/api/sessions/{MOS_SESS}/memories")
    print("SB -> MOS memories:", st, len(body))

    print("\n== 5. explain IDOR: SB uses a knowledge_point_id from the MOS session ==")
    st, body = req("GET", f"/api/sessions/{MOS_SESS}/knowledge-points")
    foreign_kp = body[0] if body else None
    if foreign_kp:
        st2, body2 = req(
            "POST",
            f"/api/sessions/{SB}/explain",
            {"knowledge_point_id": foreign_kp["id"], "query": None},
        )
        print(f"foreign KP id={foreign_kp['id']} name={foreign_kp['name']!r}")
        print(
            "SB explain with foreign KP:",
            st2,
            json.dumps(body2, ensure_ascii=False)[:300],
        )

    print("\n== 6. SB writes into SA's memory scope (should be blocked, is it?) ==")
    st, body = req(
        "POST",
        f"/api/sessions/{SA}/memories",
        {"kind": "note", "text": "SB 向 SA 的 scope 写入的越权内容"},
    )
    print("SB -> SA memory write:", st, json.dumps(body, ensure_ascii=False)[:200])


if __name__ == "__main__":
    main()
