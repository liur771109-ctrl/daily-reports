#!/usr/bin/env python3
"""AI Tech Daily Report — Auto Generator
Collects Claude / Gemini / AI tech YouTube videos (EN/JA/ZH),
translates with Claude API, generates a beautiful HTML report.
"""

import os, sys, json, logging, re, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / '.env')
except ImportError:
    pass

try:
    import anthropic
except ImportError:
    sys.exit("Please run: pip install anthropic yt-dlp python-dotenv")

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

# ── Config ───────────────────────────────────────────────────────────
YOUTUBE_API_KEY   = os.getenv("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUT_DIR        = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).parent)))
MAX_VIDEOS        = 3
FETCH_HOURS       = 96
CLAUDE_MODEL      = "claude-sonnet-4-6"
YT_API_BASE       = "https://www.googleapis.com/youtube/v3"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Channel List ─────────────────────────────────────────────────────
CHANNELS = [
    # Anthropic / Claude
    {"id": "",  "handle": "AnthropicAI",             "name": "Anthropic",             "lang": "en", "category": "claude"},
    {"id": "",  "handle": "DavidOndrej",              "name": "David Ondrej",          "lang": "en", "category": "claude"},
    {"id": "",  "handle": "samwitteveenai",           "name": "Sam Witteveen",         "lang": "en", "category": "claude"},
    # Google / Gemini
    {"id": "UC295-Dw4tzbADSmDecgwBuw", "handle": "GoogleforDevelopers", "name": "Google for Developers", "lang": "en", "category": "gemini"},
    {"id": "UCP4bf6IHJJQehibu6ai__cg", "handle": "GoogleDeepMind",      "name": "Google DeepMind",       "lang": "en", "category": "gemini"},
    {"id": "",  "handle": "daveebbelaar",             "name": "Dave Ebbelaar",         "lang": "en", "category": "gemini"},
    # AI Apps / Dev Tutorials
    {"id": "UCsBjURrPoezykLs9EqgamOA", "handle": "Fireship",            "name": "Fireship",              "lang": "en", "category": "aiapps"},
    {"id": "",  "handle": "matthew_berman",           "name": "Matthew Berman",        "lang": "en", "category": "industry"},
    {"id": "",  "handle": "TheAIAdvantage",           "name": "The AI Advantage",      "lang": "en", "category": "aiapps"},
    {"id": "",  "handle": "AssemblyAI",               "name": "AssemblyAI",            "lang": "en", "category": "aiapps"},
    {"id": "",  "handle": "mreflow",                  "name": "Matt Wolfe",            "lang": "en", "category": "industry"},
    {"id": "",  "handle": "TwoMinutePapers",          "name": "Two Minute Papers",     "lang": "en", "category": "industry"},
    {"id": "",  "handle": "LexFridman",               "name": "Lex Fridman",           "lang": "en", "category": "industry"},
    {"id": "",  "handle": "AICodingMastery",          "name": "AI Coding Mastery",     "lang": "en", "category": "aiapps"},
    # Japanese AI (if 404, update handle from YouTube URL)
    {"id": "UCnkp2uAFSBNjGxFBFGWFPMg", "handle": "", "name": "AIひろゆき解説",         "lang": "ja", "category": "industry"},
    {"id": "",  "handle": "KAI_AI_Japan",             "name": "KAI AI Japan",          "lang": "ja", "category": "aiapps"},
    # Chinese AI channels
    {"id": "",  "handle": "guizang",                  "name": "歸藏",                   "lang": "zh", "category": "aiapps"},
    {"id": "",  "handle": "jiqizhixin",               "name": "機器之心",                "lang": "zh", "category": "industry"},
    {"id": "",  "handle": "learnprompting",           "name": "Learn Prompting",        "lang": "zh", "category": "claude"},
    {"id": "",  "handle": "xiaohuiai",                "name": "小灰 AI",                 "lang": "zh", "category": "aiapps"},
    {"id": "",  "handle": "AIToolsChannel",           "name": "AI 工具箱",               "lang": "zh", "category": "aiapps"},
]

CAT = {
    "claude":   {"label": "Claude 動態",  "icon": "🟣", "eng": "Claude Updates",      "cls": "claude"},
    "gemini":   {"label": "Gemini 動態",  "icon": "🔵", "eng": "Gemini Updates",      "cls": "gemini"},
    "aiapps":   {"label": "AI 應用實戰", "icon": "⚡", "eng": "AI Apps in Practice", "cls": "aiapps"},
    "industry": {"label": "行業快訊",    "icon": "📰", "eng": "AI Industry News",    "cls": "industry"},
}
FLAG = {"en": "🇺🇸", "ja": "🇯🇵", "zh": "🇨🇳"}

# ── YouTube API ───────────────────────────────────────────────────────
def yt_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    url = YT_API_BASE + "/" + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning("YouTube API error: " + str(e))
        return {}

def fetch_via_api(channel_id, channel_name):
    if not (YOUTUBE_API_KEY and channel_id):
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = yt_get("search", {"part": "snippet", "channelId": channel_id,
                             "publishedAfter": cutoff, "order": "date",
                             "type": "video", "maxResults": MAX_VIDEOS})
    videos = []
    for item in data.get("items", []):
        s   = item["snippet"]
        vid = item["id"]["videoId"]
        stats = yt_get("videos", {"part": "statistics", "id": vid})
        views = 0
        if stats.get("items"):
            views = int(stats["items"][0]["statistics"].get("viewCount", 0))
        videos.append({
            "video_id": vid,
            "url": "https://www.youtube.com/watch?v=" + vid,
            "title": s["title"],
            "description": s.get("description", "")[:800],
            "published": s["publishedAt"],
            "channel": channel_name,
            "view_count": views,
        })
    log.info("[API] " + channel_name + ": " + str(len(videos)) + " videos")
    return videos

def fetch_via_ytdlp(url, channel_name):
    if not YTDLP_AVAILABLE:
        return []
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": "in_playlist",
                                "playlistend": MAX_VIDEOS * 3, "skip_download": True}) as ydl:
            info    = ydl.extract_info(url, download=False)
            entries = info.get("entries", []) if info else []
        videos = []
        for entry in entries:
            if not entry or not entry.get("id"):
                continue
            vid = entry["id"]
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                    detail = ydl.extract_info("https://www.youtube.com/watch?v=" + vid, download=False)
            except Exception:
                continue
            date_str = detail.get("upload_date", "")
            if date_str:
                pub_dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                if pub_dt < cutoff_dt:
                    continue
            videos.append({
                "video_id": vid,
                "url": "https://www.youtube.com/watch?v=" + vid,
                "title": detail.get("title", ""),
                "description": (detail.get("description") or "")[:800],
                "published": date_str,
                "channel": channel_name,
                "view_count": detail.get("view_count", 0) or 0,
            })
            if len(videos) >= MAX_VIDEOS:
                break
        log.info("[yt-dlp] " + channel_name + ": " + str(len(videos)) + " videos")
        return videos
    except Exception as e:
        log.warning("[yt-dlp] " + channel_name + " failed: " + str(e))
        return []

def fetch_channel(ch):
    cid, name, handle = ch.get("id", ""), ch["name"], ch.get("handle", "")
    videos = fetch_via_api(cid, name)
    if not videos and handle:
        videos = fetch_via_ytdlp("https://www.youtube.com/@" + handle + "/videos", name)
    if not videos and cid:
        videos = fetch_via_ytdlp("https://www.youtube.com/channel/" + cid + "/videos", name)
    return videos or []

# ── Anthropic API ─────────────────────────────────────────────────────
def test_anthropic_key():
    if not ANTHROPIC_API_KEY:
        return False
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        client.messages.create(model=CLAUDE_MODEL, max_tokens=20,
                               messages=[{"role": "user", "content": "Hi"}])
        log.info("Anthropic API OK (model: " + CLAUDE_MODEL + ")")
        return True
    except anthropic.AuthenticationError as e:
        log.error("API key invalid: " + str(e))
    except anthropic.APIConnectionError as e:
        log.error("Connection failed: " + str(e))
    except Exception as e:
        log.error("API test failed: " + type(e).__name__ + ": " + str(e))
    return False

def _set_fallback(video):
    video.setdefault("title_zh", video["title"])
    desc = video.get("description", "").strip()
    video.setdefault("summary", (desc[:200] + "...") if len(desc) > 200 else desc or "(no description)")
    video.setdefault("tags", [])

def ai_process(video, lang, category, client):
    cat_zh = {"claude": "Claude 動態", "gemini": "Gemini 動態",
              "aiapps": "AI 應用實戰", "industry": "AI 行業快訊"}.get(category, "AI 技術")
    if lang == "zh":
        lang_desc = "中文（無需翻譯標題，直接整理摘要）"
        title_note = "繁體中文標題（原標題已是中文，可適度潤色但保持原意）"
    elif lang == "ja":
        lang_desc = "日文"
        title_note = "繁體中文標題（從日文翻譯，保留技術術語英文縮寫）"
    else:
        lang_desc = "英文"
        title_note = "繁體中文標題（從英文翻譯，保留 Claude、Gemini、MCP、RAG 等英文縮寫）"
    prompt = (
        "你是專業 AI 技術分析師，專注 Claude、Gemini、LLM 應用領域。"
        "請處理以下 YouTube 影片資訊。\n\n"
        "影片語言：" + lang_desc + "\n"
        "類別：" + cat_zh + "\n"
        "頻道：" + video["channel"] + "\n"
        "標題：" + video["title"] + "\n"
        "描述：" + video.get("description", "（無）")[:500] + "\n\n"
        "請以 JSON 格式回覆：\n"
        "{\"title_zh\":\"" + title_note + "\","
        "\"summary\":\"核心摘要（繁體中文，130-180字，說明影片涵蓋的具體技術點、功能更新或應用場景）\","
        "\"tags\":[\"技術標籤1\",\"技術標籤2\",\"技術標籤3\"]}\n\n"
        "只回覆 JSON，不要任何額外文字。"
    )
    try:
        msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=600,
                                     messages=[{"role": "user", "content": prompt}])
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            r = json.loads(m.group())
            video["title_zh"] = r.get("title_zh", video["title"])
            video["summary"]  = r.get("summary", "")
            video["tags"]     = r.get("tags", [])[:5]
            log.info("   AI done: " + video["title_zh"][:40] + "...")
        else:
            log.warning("   AI format error: " + raw[:80])
            _set_fallback(video)
    except Exception as e:
        log.error("   AI failed (" + video["channel"] + "): " + type(e).__name__ + ": " + str(e))
        _set_fallback(video)
    return video

# ── HTML Generation ───────────────────────────────────────────────────
def fmt_views(n):
    if n >= 10000: return str(round(n / 10000, 1)) + "萬"
    if n >= 1000:  return str(round(n / 1000, 1)) + "K"
    return str(n) if n else "—"

def time_ago(pub):
    try:
        if "T" in str(pub):
            dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(str(pub), "%Y%m%d").replace(tzinfo=timezone.utc)
        h = int((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        if h < 1:   return "剛剛"
        if h < 24:  return str(h) + "小時前"
        return str(h // 24) + "天前"
    except Exception:
        return str(pub)

def card_html(video, ch):
    cat  = ch["category"]
    cls  = CAT[cat]["cls"]
    abbr = ch["name"][0].upper()
    tags = "".join('<span class="tag tag-' + cls + '">' + t + '</span>'
                   for t in video.get("tags", []))
    title_zh = video.get("title_zh", video.get("title", ""))
    summary  = video.get("summary", "（暫無摘要）")
    flag     = FLAG.get(ch["lang"], "")
    pub      = time_ago(video.get("published", ""))
    url      = video.get("url", "#")
    views    = fmt_views(video.get("view_count", 0))
    orig     = video.get("title", "")
    return (
        '<article class="card" data-cat="' + cat + '">'
        '<div class="card-top"><div class="channel-badge">'
        '<div class="ch-icon ' + cls + '">' + abbr + '</div>'
        '<span class="ch-name">' + ch["name"] + '</span>'
        '<span class="flag">' + flag + '</span></div>'
        '<span class="card-time">' + pub + '</span></div>'
        '<div class="card-title-orig">' + orig + '</div>'
        '<div class="card-title-zh">' + title_zh + '</div>'
        '<div class="card-summary">' + summary + '</div>'
        '<div class="card-tags">' + tags + '</div>'
        '<div class="card-footer">'
        '<a class="watch-btn" href="' + url + '" target="_blank">&#9654; 觀看影片</a>'
        '<span class="view-count">&#128065; ' + views + ' 次</span>'
        '</div></article>'
    )

def section_html(cat, items):
    if not items:
        return ""
    cfg   = CAT[cat]
    cards = "".join(card_html(v, ch) for v, ch in items)
    return (
        '<section class="section visible" data-cat="' + cfg["cls"] + '">'
        '<div class="section-header">'
        '<span class="section-pill pill-' + cfg["cls"] + '">' + cfg["icon"] + ' ' + cfg["label"] + '</span>'
        '<span class="section-title">' + cfg["eng"] + '</span>'
        '<span class="section-count">' + str(len(items)) + ' 則</span></div>'
        '<div class="card-grid">' + cards + '</div></section>'
    )

def highlight_html(top3):
    cards = ""
    for i, (v, ch) in enumerate(top3[:3], 1):
        tags = "".join('<span class="hl-tag">#' + t.lstrip("#") + '</span>'
                       for t in v.get("tags", [])[:3])
        title = v.get("title_zh", v.get("title", ""))
        url   = v.get("url", "#")
        cards += (
            '<a class="hl-card" href="' + url + '" target="_blank">'
            '<div class="hl-num">' + str(i) + '</div>'
            '<div class="hl-content">'
            '<div class="hl-ch">' + ch["name"] + '</div>'
            '<div class="hl-title">' + title + '</div>'
            '<div class="hl-tags">' + tags + '</div>'
            '</div></a>'
        )
    return (
        '<div class="highlight-strip"><div class="highlight-inner">'
        '<div class="hl-label">今日亮點</div>'
        '<div class="hl-grid">' + cards + '</div>'
        '</div></div>'
    )

CSS = ("*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}"
":root{--bg:#07091a;--surf:#0d1030;--card:#111428;--card2:#181c3a;--bdr:#1e2550;--bdr2:#2d3878;"
"--blue:#60a5fa;--blue-bg:rgba(96,165,250,.08);--blue-b:rgba(96,165,250,.25);"
"--purple:#a78bfa;--purple-bg:rgba(167,139,250,.08);--purple-b:rgba(167,139,250,.25);"
"--cyan:#22d3ee;--cyan-bg:rgba(34,211,238,.08);--cyan-b:rgba(34,211,238,.25);"
"--green:#34d399;--green-bg:rgba(52,211,153,.08);--green-b:rgba(52,211,153,.25);"
"--gold:#fbbf24;--t1:#e2e8ff;--t2:#7b8cc8;--tm:#3d4d80;--r:14px;"
"--grad1:linear-gradient(135deg,#6366f1,#8b5cf6,#06b6d4)}"
"html{scroll-behavior:smooth}"
"body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang TC','Noto Sans TC',sans-serif;background:var(--bg);color:var(--t1);line-height:1.6;min-height:100vh}"
"body::before{content:'';position:fixed;inset:0;background:radial-gradient(ellipse 80% 50% at 20% 10%,rgba(99,102,241,.07),transparent 60%),radial-gradient(ellipse 60% 40% at 80% 80%,rgba(139,92,246,.06),transparent 60%);pointer-events:none;z-index:0}"
".site-header{position:sticky;top:0;z-index:100;background:rgba(7,9,26,.85);backdrop-filter:blur(16px);border-bottom:1px solid var(--bdr);padding:0 28px}"
".header-inner{max-width:1300px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:68px}"
".logo-block{display:flex;align-items:center;gap:14px}"
".logo-icon{width:40px;height:40px;border-radius:10px;background:var(--grad1);display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 0 20px rgba(99,102,241,.4)}"
".logo-text{font-size:19px;font-weight:800}.logo-text .g{background:var(--grad1);-webkit-background-clip:text;-webkit-text-fill-color:transparent}"
".header-right{display:flex;align-items:center;gap:12px}"
".date-pill{font-size:12px;color:var(--t2);background:var(--blue-bg);border:1px solid var(--blue-b);padding:5px 14px;border-radius:20px}"
".live-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;animation:pulse 2s ease-in-out infinite}"
".gen-tag{font-size:11px;color:var(--cyan);background:var(--cyan-bg);border:1px solid var(--cyan-b);padding:4px 11px;border-radius:20px;display:flex;align-items:center;gap:6px}"
"@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}"
".hero{padding:48px 28px 36px;position:relative;z-index:1}"
".hero-inner{max-width:1300px;margin:0 auto}"
".hero-eyebrow{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--purple);margin-bottom:10px}"
".hero h1{font-size:clamp(24px,4vw,38px);font-weight:900;margin-bottom:10px;line-height:1.2}"
".hero h1 .a{background:var(--grad1);-webkit-background-clip:text;-webkit-text-fill-color:transparent}"
".hero-sub{font-size:14px;color:var(--t2);margin-bottom:28px}"
".stats-row{display:flex;flex-wrap:wrap;gap:10px}"
".stat-chip{display:flex;align-items:center;gap:9px;background:var(--card);border:1px solid var(--bdr);border-radius:10px;padding:9px 18px;font-size:13px}"
".dot{width:7px;height:7px;border-radius:50%}.num{font-weight:800;font-size:15px}.lbl{color:var(--tm)}"
".da{background:var(--grad1)}.db{background:var(--blue)}.dp{background:var(--purple)}.dc{background:var(--cyan)}.dg{background:var(--green)}"
".highlight-strip{background:linear-gradient(135deg,rgba(99,102,241,.12),rgba(139,92,246,.10),rgba(6,182,212,.08));border-top:1px solid var(--bdr);border-bottom:1px solid var(--bdr);padding:28px;position:relative;z-index:1}"
".highlight-inner{max-width:1300px;margin:0 auto}"
".hl-label{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:16px;display:flex;align-items:center;gap:8px}"
".hl-label::before{content:'\\2605';font-size:13px}"
".hl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}"
".hl-card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:var(--r);padding:18px;display:flex;gap:14px;align-items:flex-start;transition:background .2s,transform .15s;cursor:pointer;text-decoration:none;color:inherit}"
".hl-card:hover{background:rgba(255,255,255,.07);transform:translateY(-2px)}"
".hl-num{width:32px;height:32px;border-radius:8px;background:var(--grad1);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:14px;flex-shrink:0}"
".hl-content .hl-ch{font-size:11px;color:var(--t2);margin-bottom:4px}"
".hl-content .hl-title{font-size:14px;font-weight:700;line-height:1.4;margin-bottom:6px}"
".hl-content .hl-tags{display:flex;flex-wrap:wrap;gap:5px}"
".hl-tag{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:600;background:var(--purple-bg);color:var(--purple);border:1px solid var(--purple-b)}"
".tab-nav{background:var(--surf);border-bottom:1px solid var(--bdr);padding:0 28px;overflow-x:auto;position:sticky;top:68px;z-index:90}"
".tab-list{max-width:1300px;margin:0 auto;display:flex;list-style:none;gap:4px}"
".tab-btn{display:flex;align-items:center;gap:8px;padding:15px 22px;font-size:14px;font-weight:600;color:var(--tm);background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;transition:all .2s}"
".tab-btn:hover{color:var(--t2)}.tab-count{font-size:11px;background:rgba(255,255,255,.07);padding:1px 8px;border-radius:10px}"
".tab-btn[data-cat=all].active{border-color:var(--gold);color:var(--gold)}"
".tab-btn[data-cat=claude].active{border-color:var(--purple);color:var(--purple)}"
".tab-btn[data-cat=gemini].active{border-color:var(--blue);color:var(--blue)}"
".tab-btn[data-cat=aiapps].active{border-color:var(--cyan);color:var(--cyan)}"
".tab-btn[data-cat=industry].active{border-color:var(--green);color:var(--green)}"
".main{max-width:1300px;margin:0 auto;padding:32px 28px 80px;position:relative;z-index:1}"
".section{margin-bottom:44px}.section[data-cat]{display:none}.section.visible{display:block}"
".section-header{display:flex;align-items:center;gap:14px;margin-bottom:22px;padding-bottom:14px;border-bottom:1px solid var(--bdr)}"
".section-pill{display:inline-flex;align-items:center;gap:7px;padding:5px 16px;border-radius:20px;font-size:13px;font-weight:700}"
".pill-claude{background:var(--purple-bg);border:1px solid var(--purple-b);color:var(--purple)}"
".pill-gemini{background:var(--blue-bg);border:1px solid var(--blue-b);color:var(--blue)}"
".pill-aiapps{background:var(--cyan-bg);border:1px solid var(--cyan-b);color:var(--cyan)}"
".pill-industry{background:var(--green-bg);border:1px solid var(--green-b);color:var(--green)}"
".section-title{font-size:19px;font-weight:800}.section-count{margin-left:auto;font-size:12px;color:var(--tm)}"
".card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:18px}"
".card{background:var(--card);border:1px solid var(--bdr);border-radius:var(--r);padding:22px;display:flex;flex-direction:column;gap:13px;transition:background .2s,border-color .2s,transform .15s,box-shadow .2s;position:relative;overflow:hidden}"
".card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}"
".card[data-cat=claude]::before{background:linear-gradient(90deg,#7c3aed,#a78bfa)}"
".card[data-cat=gemini]::before{background:linear-gradient(90deg,#2563eb,#60a5fa)}"
".card[data-cat=aiapps]::before{background:linear-gradient(90deg,#0891b2,#22d3ee)}"
".card[data-cat=industry]::before{background:linear-gradient(90deg,#059669,#34d399)}"
".card:hover{background:var(--card2);border-color:var(--bdr2);transform:translateY(-3px);box-shadow:0 8px 32px rgba(0,0,0,.4)}"
".card-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}"
".channel-badge{display:flex;align-items:center;gap:8px}"
".ch-icon{width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800}"
".ch-icon.claude{background:var(--purple-bg);color:var(--purple)}.ch-icon.gemini{background:var(--blue-bg);color:var(--blue)}"
".ch-icon.aiapps{background:var(--cyan-bg);color:var(--cyan)}.ch-icon.industry{background:var(--green-bg);color:var(--green)}"
".ch-name{font-size:12px;font-weight:700;color:var(--t2)}.flag{font-size:13px}.card-time{font-size:11px;color:var(--tm);white-space:nowrap}"
".card-title-orig{font-size:11px;color:var(--tm);font-style:italic;line-height:1.5;border-left:2px solid var(--bdr2);padding-left:9px}"
".card-title-zh{font-size:15px;font-weight:800;line-height:1.4}"
".card-summary{font-size:13px;color:var(--t2);line-height:1.7;flex:1}"
".card-tags{display:flex;flex-wrap:wrap;gap:6px}"
".tag{font-size:11px;padding:3px 10px;border-radius:10px;font-weight:600}"
".tag-claude{background:var(--purple-bg);color:var(--purple);border:1px solid var(--purple-b)}"
".tag-gemini{background:var(--blue-bg);color:var(--blue);border:1px solid var(--blue-b)}"
".tag-aiapps{background:var(--cyan-bg);color:var(--cyan);border:1px solid var(--cyan-b)}"
".tag-industry{background:var(--green-bg);color:var(--green);border:1px solid var(--green-b)}"
".card-footer{display:flex;align-items:center;justify-content:space-between;padding-top:12px;border-top:1px solid var(--bdr)}"
".watch-btn{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:var(--t1);text-decoration:none;padding:6px 14px;background:linear-gradient(135deg,rgba(99,102,241,.3),rgba(139,92,246,.2));border:1px solid rgba(139,92,246,.4);border-radius:8px;transition:all .2s}"
".watch-btn:hover{background:linear-gradient(135deg,rgba(99,102,241,.5),rgba(139,92,246,.4));border-color:var(--purple);box-shadow:0 0 12px rgba(139,92,246,.3)}"
".view-count{font-size:11px;color:var(--tm)}"
".site-footer{border-top:1px solid var(--bdr);padding:28px;text-align:center;position:relative;z-index:1}"
".footer-inner p{font-size:12px;color:var(--tm);margin-bottom:8px}"
".footer-inner .grad-text{background:var(--grad1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:700}"
"::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--bdr2);border-radius:3px}"
"@media(max-width:640px){.header-inner{height:58px}.gen-tag{display:none}.hero{padding:28px 16px 24px}.main{padding:20px 16px 60px}.card-grid{grid-template-columns:1fr}.highlight-strip{padding:20px 16px}}")

JS = ("function switchTab(btn){"
"document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));"
"btn.classList.add('active');"
"var cat=btn.dataset.cat;"
"document.querySelectorAll('.section').forEach(function(sec){"
"if(cat==='all')sec.classList.add('visible');"
"else sec.classList.toggle('visible',sec.dataset.cat===cat);});}"
"var obs=new IntersectionObserver(function(e){e.forEach(function(x){"
"if(x.isIntersecting){x.target.style.opacity='1';x.target.style.transform='translateY(0)';}})},{threshold:.05});"
"document.querySelectorAll('.card').forEach(function(c){"
"c.style.opacity='0';c.style.transform='translateY(18px)';"
"c.style.transition='opacity .4s,transform .4s,background .2s,box-shadow .2s';obs.observe(c);});")

def generate_html(all_videos, report_date):
    by_cat = {k: [] for k in CAT}
    for v, ch in all_videos:
        by_cat.setdefault(ch.get("category", "industry"), []).append((v, ch))
    total  = len(all_videos)
    counts = {k: len(v) for k, v in by_cat.items()}
    gt     = datetime.now().strftime("%Y-%m-%d %H:%M")
    wdays  = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    dt     = datetime.strptime(report_date, "%Y-%m-%d")
    ddisp  = str(dt.year) + " 年 " + str(dt.month) + " 月 " + str(dt.day) + " 日（" + wdays[dt.weekday()] + "）"
    top3   = all_videos[:3]
    hl     = highlight_html(top3) if top3 else ""
    secs   = "".join(section_html(c, by_cat[c]) for c in ["claude", "gemini", "aiapps", "industry"])
    ch_names = " · ".join(ch["name"] for ch in CHANNELS)
    return (
        '<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0"/>'
        '<title>每日 AI 技術情報 — ' + report_date + '</title>'
        '<style>' + CSS + '</style></head><body>'
        '<header class="site-header"><div class="header-inner">'
        '<div class="logo-block"><div class="logo-icon">🤖</div>'
        '<div class="logo-text">每日<span class="g">AI 技術</span>情報</div></div>'
        '<div class="header-right">'
        '<div class="date-pill">📅 ' + ddisp + '</div>'
        '<div class="gen-tag"><div class="live-dot"></div>自動生成 ' + gt + '</div>'
        '</div></div></header>'
        '<section class="hero"><div class="hero-inner">'
        '<div class="hero-eyebrow">AI DAILY INTELLIGENCE</div>'
        '<h1>今日 <span class="a">AI 技術動態</span> 彙整</h1>'
        '<p class="hero-sub">從 ' + str(len(CHANNELS)) + ' 個精選 YouTube 頻道（英/日/中）自動抓取 · Claude AI 翻譯摘要</p>'
        '<div class="stats-row">'
        '<div class="stat-chip"><div class="dot da"></div><span class="num">' + str(total) + '</span><span class="lbl">今日影片</span></div>'
        '<div class="stat-chip"><div class="dot dp"></div><span class="num">' + str(counts["claude"]) + '</span><span class="lbl">Claude</span></div>'
        '<div class="stat-chip"><div class="dot db"></div><span class="num">' + str(counts["gemini"]) + '</span><span class="lbl">Gemini</span></div>'
        '<div class="stat-chip"><div class="dot dc"></div><span class="num">' + str(counts["aiapps"]) + '</span><span class="lbl">AI 應用</span></div>'
        '<div class="stat-chip"><div class="dot dg"></div><span class="num">' + str(counts["industry"]) + '</span><span class="lbl">行業快訊</span></div>'
        '</div></div></section>'
        + hl +
        '<nav class="tab-nav"><ul class="tab-list">'
        '<li><button class="tab-btn active" data-cat="all" onclick="switchTab(this)">全部 <span class="tab-count">' + str(total) + '</span></button></li>'
        '<li><button class="tab-btn" data-cat="claude" onclick="switchTab(this)">🟣 Claude 動態 <span class="tab-count">' + str(counts["claude"]) + '</span></button></li>'
        '<li><button class="tab-btn" data-cat="gemini" onclick="switchTab(this)">🔵 Gemini 動態 <span class="tab-count">' + str(counts["gemini"]) + '</span></button></li>'
        '<li><button class="tab-btn" data-cat="aiapps" onclick="switchTab(this)">⚡ AI 應用實戰 <span class="tab-count">' + str(counts["aiapps"]) + '</span></button></li>'
        '<li><button class="tab-btn" data-cat="industry" onclick="switchTab(this)">📰 行業快訊 <span class="tab-count">' + str(counts["industry"]) + '</span></button></li>'
        '</ul></nav>'
        '<main class="main">' + secs + '</main>'
        '<footer class="site-footer"><div class="footer-inner">'
        '<p>📺 ' + ch_names + '</p>'
        '<p>🤖 <span class="grad-text">Claude ' + CLAUDE_MODEL + '</span> 自動翻譯摘要 · ' + gt + '</p>'
        '<p>⚠ 本報告僅供技術資訊參考，不構成任何投資建議。</p>'
        '</div></footer>'
        '<script>' + JS + '</script></body></html>'
    )

# ── Main ─────────────────────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("  AI 技術情報每日系統 啟動")
    log.info("=" * 55)
    yt_status = "OK (" + YOUTUBE_API_KEY[:8] + "...)" if YOUTUBE_API_KEY else "NOT SET"
    ai_status = "OK (" + ANTHROPIC_API_KEY[:12] + "...)" if ANTHROPIC_API_KEY else "NOT SET"
    log.info("YouTube API Key : " + yt_status)
    log.info("Anthropic Key   : " + ai_status)
    log.info("Fetch hours     : " + str(FETCH_HOURS))

    ai_ok = False
    if ANTHROPIC_API_KEY:
        log.info("Testing Anthropic API...")
        ai_ok = test_anthropic_key()
    ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if (ANTHROPIC_API_KEY and ai_ok) else None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / (report_date + "_ai_report.html")
    log.info("Output: " + str(output_path))
    log.info("-" * 55)

    all_videos = []
    for ch in CHANNELS:
        log.info("Fetching: " + ch["name"] + " ...")
        videos = fetch_channel(ch)
        if not videos:
            log.info("   -> no new videos")
            continue
        for video in videos:
            if ai_client:
                log.info("   AI: " + video["title"][:50] + "...")
                video = ai_process(video, ch["lang"], ch["category"], ai_client)
            else:
                _set_fallback(video)
            all_videos.append((video, ch))

    log.info("-" * 55)
    log.info("Total videos: " + str(len(all_videos)))
    if not all_videos:
        log.warning("No videos today, generating empty report")
    html = generate_html(all_videos, report_date)
    output_path.write_text(html, encoding="utf-8")
    log.info("Saved: " + str(output_path))

if __name__ == "__main__":
    main()
