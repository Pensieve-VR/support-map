#!/usr/bin/env python3
"""노션 지원사업 DB에서 지도에 올릴 행을 읽어 JSON 배열로 쓴다.

쓰는 법 (GitHub Actions가 매일 돌린다)
  NOTION_TOKEN=... python3 tools/notion_export.py 행.json
  python3 tools/update_data.py 행.json --full

- 읽기만 한다. 노션에는 아무것도 쓰지 않는다.
- 마감 전(마감일이 오늘 이후이거나 비어 있음)이고 출처가 채워진 행만 가져온다.
  출처가 빈 행은 팀이 직접 만든 로드맵·메모 행이라 지도에 내보내지 않는다.
- 공개용이라 사업명·주관기관·출처·지역·신청 대상·유형·금액·마감일·요약·공고 URL만 꺼낸다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DATABASE_ID = "2cc49e2256c180a8b687d2d7ff8a4752"  # 노션 '지원사업' DB
API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
KST = timezone(timedelta(hours=9))
FIELDS = ["사업명", "주관기관", "출처", "지역", "신청 대상", "유형", "금액", "마감일", "요약", "공고 URL"]


def call(path, body, token):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": "Bearer " + token, "Notion-Version": VERSION, "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(float(e.headers.get("Retry-After") or 2 ** attempt))
                continue
            raise SystemExit(f"노션 API 오류 {e.code}: {e.read().decode(errors='replace')[:300]}")
    raise SystemExit("노션 API 재시도 초과")


def plain(prop):
    """노션 속성 하나를 단순한 값으로."""
    if not prop:
        return None
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in v or []).strip()
    if t == "select":
        return v["name"] if v else ""
    if t == "multi_select":
        return [x["name"] for x in v or []]
    if t == "number":
        return v
    if t == "date":
        return (v or {}).get("start") or ""
    if t == "url":
        return v or ""
    return None


def to_row(page):
    p = page.get("properties", {})
    row = {k: plain(p.get(k)) for k in FIELDS}
    row["마감일"] = (row.get("마감일") or "")[:10]
    return row


def main():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("NOTION_TOKEN이 없다. GitHub 저장소 Settings › Secrets에 넣는다.")
    out = sys.argv[1] if len(sys.argv) > 1 else "rows.json"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    body = {
        "page_size": 100,
        "filter": {"and": [
            {"property": "출처", "select": {"is_not_empty": True}},
            {"or": [
                {"property": "마감일", "date": {"is_empty": True}},
                {"property": "마감일", "date": {"on_or_after": today}},
            ]},
        ]},
    }
    rows, cursor, pages = [], None, 0
    while True:
        if cursor:
            body["start_cursor"] = cursor
        j = call(f"/databases/{DATABASE_ID}/query", body, token)
        rows += [to_row(pg) for pg in j.get("results", []) if not pg.get("archived") and not pg.get("in_trash")]
        pages += 1
        if not j.get("has_more"):
            break
        cursor = j.get("next_cursor")
        time.sleep(0.35)  # 초당 3건 한도 아래로
    rows = [r for r in rows if r.get("사업명")]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"노션에서 {len(rows)}건 읽음 ({pages}쪽, {today} 기준) → {out}")
    if len(rows) < 50:
        raise SystemExit("읽은 행이 너무 적다. DB 공유(연결)나 필터를 확인한다. data.json은 바꾸지 않는다.")


if __name__ == "__main__":
    main()
