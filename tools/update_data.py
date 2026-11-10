#!/usr/bin/env python3
"""노션 지원사업 DB 행을 지도용 data.json에 합친다.

쓰는 법
  python3 tools/update_data.py 새행.json            # 새 행만 합치기 (공고 URL이 같으면 덮어씀)
  python3 tools/update_data.py 전체행.json --full   # 마감 전 공고 전체로 다시 만들기

입력 JSON: 노션 지원사업 DB 행의 배열. 각 행은 아래 키를 쓴다 (없는 키는 비워도 된다).
  사업명, 주관기관, 지역(문자열 배열), 신청 대상(문자열 배열), 유형, 금액(숫자),
  마감일("YYYY-MM-DD"), 요약, 공고 URL
노션 query 결과처럼 배열 칸이 JSON 문자열('["전국"]')이어도 된다. "date:마감일:start"도 읽는다.

공개용이라 팀 내부 칸(상태, 담당자, 결과메모, 확인할 점, 관련 업무·회의록·재원)은 읽지 않는다.
시도와 지원 형태는 주관기관·사업명·요약의 낱말로 자동 분류한다 (노션 속성은 바꾸지 않는다).
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data.json"
KST = timezone(timedelta(hours=9))
FIELDS = ["사업명", "주관기관", "시도", "지원형태", "마감일", "금액", "신청대상", "신청범위", "링크", "요약"]

SIDO = [
    ("서울", ["서울", "강남", "관악", "성동", "노원", "구로", "마포", "서초", "송파", "영등포", "금천", "동대문", "성북", "도봉", "은평", "종로", "용산", "양천", "중랑", "광진", "동작", "서대문", "강동구", "강북", "G밸리"]),
    ("부산", ["부산"]),
    ("대구", ["대구"]),
    ("인천", ["인천", "송도"]),
    ("광주", ["광주광역", "광주시", "광주과학", "광주"]),
    ("대전", ["대전", "KAIST", "카이스트", "대덕"]),
    ("울산", ["울산", "울주", "UNIST", "유니스트", "UBPI", "UIPA"]),
    ("세종", ["세종"]),
    ("경기", ["경기", "수원", "성남", "용인", "부천", "안산", "안양", "남양주", "화성", "동탄", "평택", "의정부", "시흥", "파주", "김포", "광명", "군포", "하남", "오산", "이천", "안성", "의왕", "양주", "구리", "포천", "동두천", "과천", "여주", "가평", "양평", "연천", "판교", "고양"]),
    ("강원", ["강원", "춘천", "원주", "강릉", "동해", "태백", "속초", "삼척", "홍천", "횡성", "영월", "평창", "정선", "철원", "화천", "양구", "인제", "양양", "상지대", "한림대"]),
    ("충북", ["충북", "충청북", "청주", "충주", "제천", "보은", "옥천", "영동", "증평", "진천", "괴산", "음성", "단양"]),
    ("충남", ["충남", "충청남", "천안", "공주", "보령", "아산", "서산", "논산", "계룡", "당진", "금산", "부여", "서천", "청양", "홍성", "예산", "태안", "건양대"]),
    ("전북", ["전북", "전라북", "전주", "군산", "익산", "정읍", "남원", "김제", "완주", "진안", "무주", "장수", "임실", "순창", "고창", "부안"]),
    ("전남", ["전남", "전라남", "목포", "여수", "순천", "나주", "광양", "담양", "곡성", "구례", "고흥", "보성", "화순", "장흥", "강진", "해남", "영암", "무안", "함평", "영광", "장성", "완도", "진도", "신안"]),
    ("경북", ["경북", "경상북", "포항", "경주", "김천", "안동", "구미", "영주", "영천", "상주", "문경", "경산", "의성", "청송", "영양", "영덕", "청도", "고령", "성주", "칠곡", "예천", "봉화", "울진", "울릉", "포스텍", "POSTECH"]),
    ("경남", ["경남", "경상남", "창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령", "함안", "창녕", "남해", "하동", "산청", "함양", "거창", "합천"]),
    ("제주", ["제주", "서귀포"]),
]
# 이름에 다른 지역 낱말이 든 서울 학교들
OVERRIDE = [("세종사이버대", "서울"), ("세종대", "서울"), ("국민대", "서울"), ("광운대", "서울"), ("중앙대", "서울"),
            ("한양대", "서울"), ("연세대", "서울"), ("고려대", "서울"), ("삼육대", "서울"), ("한국외국어대", "서울")]

TARGET = {"예비창업": "예", "창업 기업": "창", "중소기업": "중", "소상공인": "소", "대학(원)생": "대",
          "청년": "청", "누구나": "누", "개인": "개", "팀": "팀", "기타": "기"}
URL_PREFIX = {"b": "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_",
              "k": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=",
              "w": "https://www.wevity.com/?c=find&s=1&gbn=view&ix="}


def find_sido(s):
    if not s:
        return None
    for key, g in OVERRIDE:
        if key in s:
            return g
    best, pos = None, 10 ** 9
    for g, keys in SIDO:
        for k in keys:
            i = s.find(k)
            if 0 <= i < pos:
                best, pos = g, i
    return best


def region(org, name):
    """공고 낸 곳의 시도. 못 찾으면 '전국'(중앙 기관·전국 단위)."""
    o = re.sub("경기신용보증재단|소상공인시장진흥공단", "", org or "")
    return find_sido(o) or find_sido(name) or ("경기" if "경기신용보증재단" in (org or "") else "전국")


def kind(typ, text):
    """지원 형태 9종: F 자금·보조, L 융자·보증, S 공간·장비, H 인력·고용, C 컨설팅·기술,
    M 판로·마케팅, E 교육·행사, P 공모전·포상, X 기타"""
    s = text or ""
    if typ == "공모전": return "P"
    if typ == "입주·공간": return "S"
    if re.search("융자|보증|이차보전|이자|대출|팩토링", s): return "L"
    if re.search("일경험|채용|인턴|고용|인력|일자리|취업|근로자|내일채움|E-7|귀화|휴가", s): return "H"
    if typ == "교육·행사": return "E"
    if re.search("공모|경진|챌린지|해커톤|콘테스트|포상|어워드|시상", s): return "P"
    if re.search("입주|장비|GPU|공간|보육센터", s): return "S"
    if re.search("사업화|사업비|창업자금|지원금|보조금|정착|인센티브|장려금|보상금", s): return "F"
    if re.search("수출|판로|입점|마케팅|전시|박람회|상담회|바이어|라이브커머스|해외|거래선|광고|홍보|유통", s): return "M"
    if re.search("컨설팅|바우처|멘토링|자문|진단|법률|인증|시험|검증|실증|기술개발|기술지원|지식재산|특허|IP|스마트공장|R&D|코칭|기술나눔", s): return "C"
    if re.search("교육|아카데미|캠프|세미나|행사|데모데이|네트워킹|포럼|밋업|IR", s): return "E"
    if typ == "지원사업" or re.search("지원|모집", s): return "F"
    return "X"


def short_url(u):
    u = (u or "").strip()
    for k, p in URL_PREFIX.items():
        if u.startswith(p):
            return k + u[len(p):]
    return "~" + u if u else ""


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    v = str(v).strip()
    if v.startswith("["):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in v.split(",") if x.strip()]


def to_row(r):
    name = (r.get("사업명") or "").strip()
    if not name:
        return None
    org = (r.get("주관기관") or "").strip()
    summ = (r.get("요약") or "").strip()
    reg = as_list(r.get("지역"))
    deadline = (r.get("마감일") or r.get("date:마감일:start") or "")[:10]
    amt = r.get("금액")
    amt = int(amt) if isinstance(amt, (int, float)) else None
    targets = "".join(TARGET.get(t, "") for t in as_list(r.get("신청 대상")))
    scope = "N" if "전국" in reg else "L"
    return [name[:47] + "…" if len(name) > 48 else name, org[:23] + "…" if len(org) > 24 else org,
            region(org, name), kind(r.get("유형") or "", name + " " + summ), deadline, amt, targets, scope,
            short_url(r.get("공고 URL")), summ]


def key(row):
    return row[8] or ("name:" + row[0])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if isinstance(src, dict):
        src = src.get("results") or src.get("rows") or []
    full = "--full" in sys.argv
    today = datetime.now(KST).strftime("%Y-%m-%d")

    rows = {}
    if not full and DATA.exists():
        for r in json.loads(DATA.read_text(encoding="utf-8"))["rows"]:
            rows[key(r)] = r
    before = len(rows)
    added = updated = 0
    for r in src:
        row = to_row(r)
        if not row:
            continue
        k = key(row)
        if k in rows:
            updated += 1
        else:
            added += 1
        rows[k] = row
    # 마감 지난 공고는 뺀다 (마감일이 없으면 상시로 보고 남긴다)
    kept = [r for r in rows.values() if not r[4] or r[4] >= today]
    kept.sort(key=lambda r: (r[4] or "9999", r[0]))
    DATA.write_text(json.dumps({"updated": today, "fields": FIELDS, "rows": kept},
                               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"기존 {before}건 · 새로 {added}건 · 고침 {updated}건 · 마감 지나 뺌 {len(rows) - len(kept)}건 → {len(kept)}건 ({today})")


if __name__ == "__main__":
    main()
