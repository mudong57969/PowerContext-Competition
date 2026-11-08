"""UAT2: manual confirm (new course) + low-confidence candidates + correct flow."""

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8001"
SA = "27a291634c6f4297"


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
        return exc.code, {}


def main() -> None:
    print("== 1. confirm the mis-classified data-structures doc as a NEW course ==")
    st, body = req(
        "POST",
        "/api/documents/2000002/confirm",
        {"course": "数据结构与算法", "chapter": "线性表", "knowledge_points": []},
    )
    print("confirm:", st, json.dumps(body, ensure_ascii=False))

    print("\n== 2. upload a low-confidence doc into SA ==")
    st, body = req("GET", f"/api/sessions/{SA}/documents")
    print(
        "SA documents before:",
        [(d["id"], d["filename"], d["classify_status"]) for d in body],
    )
    data = (
        "# 复习提纲\n随机变量 分布\n本文是复习提纲，内容较简略，仅供自测使用。\n"
    ).encode()
    r = urllib.request.Request(
        f"{BASE}/api/sessions/{SA}/documents", data=None, method="POST"
    )
    boundary = "uat2boundary"
    body_bytes = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="sparse_notes_uat2.md"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    r = urllib.request.Request(
        f"{BASE}/api/sessions/{SA}/documents",
        data=body_bytes,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(r, timeout=120) as resp:
        up = json.loads(resp.read())
    res = up["results"][0]
    print("upload sparse doc:", json.dumps(res, ensure_ascii=False)[:400])

    print("\n== 3. correct the low-confidence doc to a custom course ==")
    st, body = req(
        "POST",
        f"/api/documents/{res['id']}/correct",
        {
            "course": "概率论与数理统计",
            "chapter": "随机变量",
            "knowledge_points": ["随机变量"],
        },
    )
    print("correct:", st, json.dumps(body, ensure_ascii=False))

    print("\n== 4. SA documents after confirm/correct ==")
    st, body = req("GET", f"/api/sessions/{SA}/documents")
    for d in body:
        print(
            f"  id={d['id']} {d['filename']}: {d['classify_status']} conf={d['classify_confidence']} course={d['course']} chapter={d['chapter']} kps={d['knowledge_points']}"
        )

    st, body = req("GET", f"/api/sessions/{SA}/courses")
    print(
        "SA courses:",
        [(c["id"], c["name"], c["status"], c["confidence"]) for c in body],
    )


if __name__ == "__main__":
    main()
