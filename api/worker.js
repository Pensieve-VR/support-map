// 창업 지원사업 지도 하트(관심) 서버 — Cloudflare Worker + D1
// 배포: Cloudflare 대시보드 Worker 'support-map-api', D1 바인딩 이름 DB, 주소 map-api.pensieve.kr
//
// GET  /counts                    → {"counts": {"공고키": 하트수, ...}}
// POST /like {key, vid, on}       → {"key", "count", "on"}
//
// 공고키: 지도 data.json의 링크 칸(b…, k…, w…, ~https://…) 또는 "name:사업명"
// vid: 브라우저마다 만든 임의 문자열(로그인 없음). 같은 브라우저는 공고 하나에 하트 하나.
// 인터넷 주소는 저장하지 않고, 소금 친 해시만 한 시간 안 누름 횟수 제한에 쓴다.
//
// D1 스키마 (api/schema.sql)
//   CREATE TABLE likes (key TEXT NOT NULL, vid TEXT NOT NULL, iph TEXT, ts INTEGER NOT NULL, PRIMARY KEY (key, vid));
//   CREATE INDEX likes_iph_ts ON likes (iph, ts);

const ORIGINS = ["https://map.pensieve.kr", "http://map.pensieve.kr", "http://localhost:8765"];
const HOURLY_LIMIT = 30;      // 같은 주소에서 한 시간에 누를 수 있는 하트 수
const SALT = "pensieve-map-likes-v1";

function cors(req) {
  const o = req.headers.get("Origin") || "";
  return {
    "Access-Control-Allow-Origin": ORIGINS.includes(o) ? o : ORIGINS[0],
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(req, body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(req), ...extra },
  });
}

async function sha(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].slice(0, 12).map((x) => x.toString(16).padStart(2, "0")).join("");
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });

    if (req.method === "GET" && url.pathname === "/counts") {
      const { results } = await env.DB.prepare("SELECT key, COUNT(*) AS n FROM likes GROUP BY key").all();
      const counts = {};
      for (const r of results) counts[r.key] = r.n;
      return json(req, { counts }, 200, { "Cache-Control": "public, max-age=20" });
    }

    if (req.method === "POST" && url.pathname === "/like") {
      const origin = req.headers.get("Origin") || "";
      if (!ORIGINS.includes(origin)) return json(req, { error: "허용되지 않은 곳에서 온 요청" }, 403);
      let b;
      try { b = await req.json(); } catch { return json(req, { error: "잘못된 요청" }, 400); }
      const key = String(b.key || "");
      const vid = String(b.vid || "");
      const on = b.on !== false;
      if (!key || key.length > 160 || /[\u0000-\u001f]/.test(key)) return json(req, { error: "공고 키가 이상함" }, 400);
      if (!/^[A-Za-z0-9-]{16,40}$/.test(vid)) return json(req, { error: "브라우저 표시값이 이상함" }, 400);

      if (on) {
        const ip = req.headers.get("CF-Connecting-IP") || "";
        const iph = await sha(SALT + ip);
        const now = Math.floor(Date.now() / 1000);
        const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM likes WHERE iph = ? AND ts > ?").bind(iph, now - 3600).first();
        if (recent && recent.n >= HOURLY_LIMIT) return json(req, { error: "잠시 뒤에 다시 눌러 주세요" }, 429);
        await env.DB.prepare("INSERT OR IGNORE INTO likes (key, vid, iph, ts) VALUES (?, ?, ?, ?)").bind(key, vid, iph, now).run();
      } else {
        await env.DB.prepare("DELETE FROM likes WHERE key = ? AND vid = ?").bind(key, vid).run();
      }
      const c = await env.DB.prepare("SELECT COUNT(*) AS n FROM likes WHERE key = ?").bind(key).first();
      return json(req, { key, count: c ? c.n : 0, on });
    }

    return json(req, { error: "없는 주소" }, 404);
  },
};
