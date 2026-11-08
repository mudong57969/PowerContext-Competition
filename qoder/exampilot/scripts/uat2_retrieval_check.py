"""UAT2: retrieval + citation correctness after reclassification (doc 1000002)."""

import json
import urllib.request

BASE = "http://127.0.0.1:8001"
SESS = "9e7fc0f065134af5"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> None:
    # 1) hybrid search without course filter
    r = post(
        f"/api/sessions/{SESS}/search",
        {"query": "velocity saturation", "course_id": None, "limit": 5},
    )
    print(
        f"search 'velocity saturation': mode={r['mode']} fts={r['fts_hits']} vec={r['vector_hits']} hits={len(r['hits'])}"
    )
    for h in r["hits"]:
        print(
            f"  doc={h['document_id']} file={h['filename']} course={h['course']} chapter={h['chapter']} page={h['page_number']} matched={h['matched_by']} score={h['score']}"
        )
        print(f"    text: {h['text'][:90]!r}")

    # 2) course-filtered search (course of the reclassified doc)
    with urllib.request.urlopen(
        BASE + f"/api/sessions/{SESS}/courses", timeout=30
    ) as resp:
        courses = json.loads(resp.read())
    print("courses:", [(c["id"], c["name"]) for c in courses])
    cid = next(c["id"] for c in courses if c["name"] == "数字集成电路")
    r2 = post(
        f"/api/sessions/{SESS}/search",
        {"query": "body effect", "course_id": cid, "limit": 5},
    )
    print(f"search 'body effect' (course_id={cid}): hits={len(r2['hits'])}")
    bad = [h for h in r2["hits"] if h["course"] != "数字集成电路"]
    print("hits outside filtered course:", len(bad))
    for h in r2["hits"][:3]:
        print(
            f"  doc={h['document_id']} page={h['page_number']} matched={h['matched_by']}"
        )

    # 3) explain with KP id -> sources should cite the reclassified doc
    with urllib.request.urlopen(
        BASE + f"/api/sessions/{SESS}/knowledge-points", timeout=30
    ) as resp:
        kps = json.loads(resp.read())
    print("knowledge points:", [(k["id"], k["name"]) for k in kps][:10])
    target = next(k for k in kps if k["name"] == "速度饱和")
    r3 = post(
        f"/api/sessions/{SESS}/explain",
        {"knowledge_point_id": target["id"], "query": None},
    )
    print(
        f"explain KP 速度饱和: provider={r3['provider']} sources={len(r3['sources'])}"
    )
    for s in r3["sources"][:3]:
        print(
            f"  src doc={s['document_id']} file={s['filename']} page={s['page_number']} course={s['course']} chapter={s['chapter']}"
        )


if __name__ == "__main__":
    main()
