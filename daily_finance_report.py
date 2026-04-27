#!/usr/bin/env python3
"""YouTube Finance Daily Report - Auto Generator
Uses urllib (built-in) for YouTube API — no cryptography DLL required.
"""

import os, sys, json, logging, re, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env from same directory as script
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

# ── Config ──────────────────────────────────────────────────────────
YOUTUBE_API_KEY   = os.getenv("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUT_DIR        = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).parent)))
MAX_VIDEOS        = 5
FETCH_HOURS       = 72
CLAUDE_MODEL      = "claude-sonnet-4-6"
YT_API_BASE       = "https://www.googleapis.com/youtube/v3"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

CHANNELS = [
    # ── 英文宏觀 / 財經 ──────────────────────────────────────
    {"id": "UCrM7B7SL_g1edFOnmj-SDKg", "handle": "BloombergMarketsandFinance", "name": "Bloomberg Markets",   "lang": "en", "category": "macro"},
    {"id": "UCvJJ_dzjViJCoLf5uKUTwoA",  "handle": "CNBC",                       "name": "CNBC",               "lang": "en", "category": "macro"},
    {"id": "UCFRbT6FKe4YUGqD5-O2gy_w",  "handle": "KitcoNews",                  "name": "Kitco News",         "lang": "en", "category": "macro"},
    {"id": "UCFk9ZMHzDVgAGn0Y_4kFiYg",  "handle": "Wealthion",                  "name": "Wealthion",          "lang": "en", "category": "macro"},
    {"id": "UCXEqan5R9_3JlKCqSlXCYMg",  "handle": "realvision",                 "name": "Real Vision",        "lang": "en", "category": "macro"},
    {"id": "UCQxOtDzLjKFb6NxRRJFN1UA",  "handle": "LynAldenInvestmentStrategy", "name": "Lyn Alden",          "lang": "en", "category": "macro"},
    {"id": "",                           "handle": "grahamstephan",              "name": "Graham Stephan",     "lang": "en", "category": "macro"},
    {"id": "",                           "handle": "AndreiJikh",                 "name": "Andrei Jikh",        "lang": "en", "category": "etf"},
    # ── 英文加密 ────────────────────────────────────────────
    {"id": "UCqK_GSMbpiV8spgD3ZGloLA",  "handle": "CoinBureau",                 "name": "Coin Bureau",        "lang": "en", "category": "crypto"},
    {"id": "UCnzCBPOOfBMEf_4UoiKrHhQ",  "handle": "InvestAnswers",              "name": "InvestAnswers",      "lang": "en", "category": "crypto"},
    {"id": "",                           "handle": "aantonop",                   "name": "Andreas Antonopoulos","lang": "en", "category": "crypto"},
    {"id": "",                           "handle": "AdamLivingstonBTC",          "name": "Adam Livingston",    "lang": "en", "category": "crypto"},
    # ── 中文財經 ────────────────────────────────────────────
    {"id": "",  "handle": "MeiGuYanJiuShi",   "name": "美股研究室",    "lang": "zh", "category": "macro"},
    {"id": "",  "handle": "macromicrotw",      "name": "財經M平方",     "lang": "zh", "category": "macro"},
    {"id": "",  "handle": "GoodInfoTW",        "name": "股市好消息",    "lang": "zh", "category": "macro"},
    {"id": "",  "handle": "moneymonday",       "name": "Money Monday",  "lang": "zh", "category": "macro"},
    {"id": "",  "handle": "cfjycaijing",       "name": "財經角落",      "lang": "zh", "category": "macro"},
    {"id": "",  "handle": "investwisely",      "name": "聰明理財",      "lang": "zh", "category": "etf"},
    # ── 日文財經 ────────────────────────────────────────────
    {"id": "UC7sg-8-SVQXZ3HMI9bTrZtQ",  "handle": "DanTakahashi17",  "name": "高橋ダン",  "lang": "ja", "category": "macro"},
    {"id": "UC5oGMJaEpKR_ZKYQk_b7XHZA", "handle": "ryogakucho",      "name": "両学長",    "lang": "ja", "category": "etf"},
    {"id": "",                           "handle": "jonenji",         "name": "上念司",    "lang": "ja", "category": "macro"},
]

# ── YouTube API (urllib, no extra packages) ──────────────────────────
def yt_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    url = f"{YT_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning(f"YouTube API error: {e}")
        return {}

def fetch_via_api(channel_id, channel_name):
    if not (YOUTUBE_API_KEY and channel_id):
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = yt_get("search", {"part": "snippet", "channelId": channel_id,
                             "publishedAfter": cutoff, "order": "date",
                             "type": "video", "maxResults": MAX_VIDEOS})
    items = data.get("items", [])
    videos = []
    for item in items:
        s   = item["snippet"]
        vid = item["id"]["videoId"]
        stats_data = yt_get("videos", {"part": "statistics", "id": vid})
        views = 0
        if stats_data.get("items"):
            views = int(stats_data["items"][0]["statistics"].get("viewCount", 0))
        videos.append({
            "video_id": vid,
            "url":      f"https://www.youtube.com/watch?v={vid}",
            "title":    s["title"],
            "description": s.get("description", "")[:800],
            "published":   s["publishedAt"],
            "channel":     channel_name,
            "view_count":  views,
        })
    log.info(f"[API] {channel_name}: {len(videos)} videos")
    return videos

# ── yt-dlp fallback ──────────────────────────────────────────────────
def fetch_via_ytdlp(url, channel_name):
    if not YTDLP_AVAILABLE:
        return []
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)
    opts = {"quiet": True, "extract_flat": "in_playlist",
            "playlistend": MAX_VIDEOS * 3, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info    = ydl.extract_info(url, download=False)
            entries = info.get("entries", []) if info else []
        videos = []
        for entry in entries:
            if not entry or not entry.get("id"):
                continue
            vid = entry["id"]
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                    detail = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            except Exception:
                continue
            date_str = detail.get("upload_date", "")
            if date_str:
                if datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc) < cutoff_dt:
                    continue
            videos.append({
                "video_id":   vid,
                "url":        f"https://www.youtube.com/watch?v={vid}",
                "title":      detail.get("title", ""),
                "description":(detail.get("description") or "")[:800],
                "published":  date_str,
                "channel":    channel_name,
                "view_count": detail.get("view_count", 0) or 0,
            })
            if len(videos) >= MAX_VIDEOS:
                break
        log.info(f"[yt-dlp] {channel_name}: {len(videos)} videos")
        return videos
    except Exception as e:
        log.warning(f"[yt-dlp] {channel_name} failed: {e}")
        return []

def fetch_channel(ch):
    cid, name, handle = ch.get("id",""), ch["name"], ch.get("handle","")
    videos = fetch_via_api(cid, name)
    if videos:
        return videos
    if handle:
        videos = fetch_via_ytdlp(f"https://www.youtube.com/@{handle}/videos", name)
        if videos:
            return videos
    if cid:
        videos = fetch_via_ytdlp(f"https://www.youtube.com/channel/{cid}/videos", name)
    return videos or []

# ── Anthropic API key test ───────────────────────────────────────────
def test_anthropic_key():
    if not ANTHROPIC_API_KEY:
        return False
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=20,
            messages=[{"role": "user", "content": "Hi"}]
        )
        log.info(f"✅ Anthropic API 連線正常（model: {CLAUDE_MODEL}）")
        return True
    except anthropic.AuthenticationError as e:
        log.error(f"❌ Anthropic API 金鑰無效或過期：{e}")
    except anthropic.APIConnectionError as e:
        log.error(f"❌ Anthropic API 網路連線失敗：{e}")
    except anthropic.RateLimitError as e:
        log.error(f"❌ Anthropic API 請求頻率超限：{e}")
    except Exception as e:
        log.error(f"❌ Anthropic API 測試失敗：{type(e).__name__}: {e}")
    return False

# ── Claude AI ────────────────────────────────────────────────────────
def ai_process(video, lang, category, client):
    cat_zh = {"macro":"宏觀經濟","crypto":"數字貨幣","etf":"ETF","general":"綜合財經"}.get(category,"財經")
    prompt = (
        "你是專業財經分析師。請處理以下YouTube影片資訊。\n\n"
        f"影片語言：{'英文' if lang=='en' else '日文'}\n"
        f"類別：{cat_zh}\n"
        f"頻道：{video['channel']}\n"
        f"標題：{video['title']}\n"
        f"描述：{video.get('description','（無）')[:500]}\n\n"
        '請以JSON格式回覆：\n'
        '{"title_zh":"繁體中文標題","summary":"核心摘要（繁體中文，120-180字）","tags":["標籤1","標籤2","標籤3"]}\n\n'
        '只回覆JSON，不要任何額外文字。'
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
            video["tags"]     = r.get("tags", [])[:4]
            log.info(f"   ✅ AI摘要完成：{video['title_zh'][:30]}...")
        else:
            log.warning(f"   ⚠ AI回覆格式異常：{raw[:100]}")
            _set_fallback(video)
    except anthropic.AuthenticationError:
        log.error("   ❌ AI失敗：API金鑰無效，請確認 .env 中的 ANTHROPIC_API_KEY")
        _set_fallback(video)
    except anthropic.RateLimitError:
        log.warning("   ⚠ AI失敗：請求頻率超限，稍後重試")
        _set_fallback(video)
    except Exception as e:
        log.error(f"   ❌ AI失敗（{video['channel']}）：{type(e).__name__}: {e}")
        _set_fallback(video)
    return video

def _set_fallback(video):
    """AI失敗時，用英文標題+描述填充"""
    video.setdefault("title_zh", video["title"])
    desc = video.get("description", "").strip()
    video.setdefault("summary", desc[:200] + "…" if len(desc) > 200 else desc or "（無描述）")
    video.setdefault("tags", [])

# ── HTML ─────────────────────────────────────────────────────────────
CAT = {
    "macro":   {"label":"宏觀經濟","icon":"🌐","eng":"Macro Economy",          "cls":"macro"},
    "crypto":  {"label":"數字貨幣","icon":"₿", "eng":"Crypto & Digital Assets","cls":"crypto"},
    "etf":     {"label":"ETF",    "icon":"📊","eng":"ETF & Index Funds",      "cls":"etf"},
    "general": {"label":"綜合財經","icon":"💼","eng":"General Finance",         "cls":"general"},
}
FLAG = {"en":"🇺🇸","ja":"🇯🇵"}

def fmt_views(n):
    if n >= 10000: return f"{n/10000:.1f}萬"
    if n >= 1000:  return f"{n/1000:.1f}K"
    return str(n) if n else "—"

def time_ago(pub):
    try:
        dt = datetime.fromisoformat(pub.replace("Z","+00:00")) if "T" in pub \
             else datetime.strptime(pub,"%Y%m%d").replace(tzinfo=timezone.utc)
        h = int((datetime.now(timezone.utc)-dt).total_seconds()/3600)
        return "剛剛" if h<1 else f"{h}小時前" if h<24 else f"{h//24}天前"
    except Exception:
        return pub

def card_html(video, ch):
    cat  = ch["category"]; cls = CAT[cat]["cls"]
    abbr = ch["name"][0].upper()
    tags = "".join(f'<span class="tag tag-{cls}">{t}</span>' for t in video.get("tags",[]))
    title_zh = video.get("title_zh", video.get("title",""))
    summary  = video.get("summary", "（暫無摘要）")
    return (
        f'<article class="card" data-cat="{cat}">'
        f'<div class="card-top"><div class="channel-badge">'
        f'<div class="ch-icon {cls}">{abbr}</div>'
        f'<span class="ch-name">{ch["name"]}</span>'
        f'<span class="flag">{FLAG.get(ch["lang"],"")}</span></div>'
        f'<span class="card-time">{time_ago(video.get("published",""))}</span></div>'
        f'<div class="card-title-orig">{video.get("title","")}</div>'
        f'<div class="card-title-zh">{title_zh}</div>'
        f'<div class="card-summary">{summary}</div>'
        f'<div class="card-tags">{tags}</div>'
        f'<div class="card-footer">'
        f'<a class="watch-btn" href="{video.get("url","#")}" target="_blank">▶ 觀看影片</a>'
        f'<span class="view-count">👁 {fmt_views(video.get("view_count",0))} 次</span>'
        f'</div></article>'
    )

def section_html(cat, items):
    if not items: return ""
    cfg   = CAT[cat]
    cards = "".join(card_html(v,ch) for v,ch in items)
    return (
        f'<section class="section visible" data-cat="{cfg["cls"]}">'
        f'<div class="section-header">'
        f'<span class="section-pill pill-{cfg["cls"]}">{cfg["icon"]} {cfg["label"]}</span>'
        f'<span class="section-title">{cfg["eng"]}</span>'
        f'<span class="section-count">{len(items)} 則</span></div>'
        f'<div class="card-grid">{cards}</div></section>'
    )

CSS = """*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080d16;--surf:#0e1623;--card:#131e2e;--card2:#1a2840;--bdr:#1f3050;--bdr2:#2a4070;
--gold:#f0b429;--gdim:#c8901e;--gglow:rgba(240,180,41,.15);
--mac:#38bdf8;--mac-bg:rgba(56,189,248,.1);--mac-b:rgba(56,189,248,.3);
--cry:#a78bfa;--cry-bg:rgba(167,139,250,.1);--cry-b:rgba(167,139,250,.3);
--etf:#34d399;--etf-bg:rgba(52,211,153,.1);--etf-b:rgba(52,211,153,.3);
--gen:#fb923c;--gen-bg:rgba(251,146,60,.1);--gen-b:rgba(251,146,60,.3);
--t1:#e8edf5;--t2:#8fa8c8;--tm:#4a6280;--r:12px}
html{scroll-behavior:smooth}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang TC','Noto Sans TC',sans-serif;background:var(--bg);color:var(--t1);line-height:1.6}
.site-header{background:linear-gradient(135deg,#0a1525,#0d1f38,#0a1525);border-bottom:1px solid var(--bdr);padding:0 24px;position:sticky;top:0;z-index:100}
.header-inner{max-width:1280px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:64px}
.logo-block{display:flex;align-items:center;gap:12px}
.logo-icon{width:36px;height:36px;background:linear-gradient(135deg,var(--gold),var(--gdim));border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px}
.logo-text{font-size:18px;font-weight:700}.logo-text span{color:var(--gold)}
.date-badge{font-size:13px;color:var(--t2);background:rgba(255,255,255,.05);border:1px solid var(--bdr);padding:5px 12px;border-radius:20px}
.update-tag{font-size:11px;background:var(--gglow);color:var(--gold);border:1px solid rgba(240,180,41,.3);padding:3px 10px;border-radius:20px}
.hero{background:linear-gradient(160deg,#0d1f38,#080d16 60%);border-bottom:1px solid var(--bdr);padding:40px 24px 32px}
.hero-inner{max-width:1280px;margin:0 auto}
.hero h1{font-size:clamp(22px,4vw,32px);font-weight:800;margin-bottom:8px}.hero h1 .a{color:var(--gold)}
.hero-sub{font-size:14px;color:var(--t2);margin-bottom:24px}
.stats-row{display:flex;flex-wrap:wrap;gap:12px}
.stat-chip{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--bdr);border-radius:8px;padding:8px 16px;font-size:13px}
.dot{width:8px;height:8px;border-radius:50%}.num{font-weight:700}.lbl{color:var(--tm)}
.da{background:var(--gold)}.dm{background:var(--mac)}.dc{background:var(--cry)}.de{background:var(--etf)}.dg{background:var(--gen)}
.tab-nav{background:var(--surf);border-bottom:1px solid var(--bdr);padding:0 24px;overflow-x:auto}
.tab-list{max-width:1280px;margin:0 auto;display:flex;list-style:none}
.tab-btn{display:flex;align-items:center;gap:8px;padding:14px 20px;font-size:14px;font-weight:500;color:var(--tm);background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;transition:all .2s}
.tab-btn:hover{color:var(--t2)}.tab-count{font-size:11px;background:rgba(255,255,255,.07);padding:1px 7px;border-radius:10px}
.tab-btn[data-cat=all].active{border-color:var(--gold);color:var(--gold)}
.tab-btn[data-cat=macro].active{border-color:var(--mac);color:var(--mac)}
.tab-btn[data-cat=crypto].active{border-color:var(--cry);color:var(--cry)}
.tab-btn[data-cat=etf].active{border-color:var(--etf);color:var(--etf)}
.tab-btn[data-cat=general].active{border-color:var(--gen);color:var(--gen)}
.main{max-width:1280px;margin:0 auto;padding:28px 24px 60px}
.section{margin-bottom:40px}.section[data-cat]{display:none}.section.visible{display:block}
.section-header{display:flex;align-items:center;gap:12px;margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid var(--bdr)}
.section-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 14px;border-radius:20px;font-size:13px;font-weight:700}
.pill-macro{background:var(--mac-bg);border:1px solid var(--mac-b);color:var(--mac)}
.pill-crypto{background:var(--cry-bg);border:1px solid var(--cry-b);color:var(--cry)}
.pill-etf{background:var(--etf-bg);border:1px solid var(--etf-b);color:var(--etf)}
.pill-general{background:var(--gen-bg);border:1px solid var(--gen-b);color:var(--gen)}
.section-title{font-size:18px;font-weight:700}.section-count{margin-left:auto;font-size:12px;color:var(--tm)}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--bdr);border-radius:var(--r);padding:20px;display:flex;flex-direction:column;gap:12px;transition:background .2s,border-color .2s,transform .15s;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0}
.card[data-cat=macro]::before{background:var(--mac)}.card[data-cat=crypto]::before{background:var(--cry)}
.card[data-cat=etf]::before{background:var(--etf)}.card[data-cat=general]::before{background:var(--gen)}
.card:hover{background:var(--card2);border-color:var(--bdr2);transform:translateY(-2px)}
.card-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.channel-badge{display:flex;align-items:center;gap:7px}
.ch-icon{width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700}
.ch-icon.macro{background:var(--mac-bg);color:var(--mac)}.ch-icon.crypto{background:var(--cry-bg);color:var(--cry)}
.ch-icon.etf{background:var(--etf-bg);color:var(--etf)}.ch-icon.general{background:var(--gen-bg);color:var(--gen)}
.ch-name{font-size:12px;font-weight:600;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}
.flag{font-size:14px}.card-time{font-size:11px;color:var(--tm);white-space:nowrap}
.card-title-orig{font-size:11px;color:var(--tm);font-style:italic;line-height:1.4;border-left:2px solid var(--bdr2);padding-left:8px}
.card-title-zh{font-size:15px;font-weight:700;line-height:1.4}
.card-summary{font-size:13px;color:var(--t2);line-height:1.6;flex:1}
.card-tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{font-size:11px;padding:2px 9px;border-radius:10px;font-weight:500}
.tag-macro{background:var(--mac-bg);color:var(--mac);border:1px solid var(--mac-b)}
.tag-crypto{background:var(--cry-bg);color:var(--cry);border:1px solid var(--cry-b)}
.tag-etf{background:var(--etf-bg);color:var(--etf);border:1px solid var(--etf-b)}
.tag-general{background:var(--gen-bg);color:var(--gen);border:1px solid var(--gen-b)}
.card-footer{display:flex;align-items:center;justify-content:space-between;padding-top:10px;border-top:1px solid var(--bdr)}
.watch-btn{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--gold);text-decoration:none;padding:5px 12px;border:1px solid rgba(240,180,41,.3);border-radius:6px;background:var(--gglow);transition:background .2s}
.watch-btn:hover{background:rgba(240,180,41,.25);border-color:var(--gold)}
.view-count{font-size:11px;color:var(--tm)}
.site-footer{border-top:1px solid var(--bdr);padding:24px;text-align:center}
.footer-inner{max-width:1280px;margin:0 auto}.footer-inner p{font-size:12px;color:var(--tm);margin-bottom:6px}
::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--bdr2);border-radius:3px}
@media(max-width:640px){.header-inner{height:56px}.update-tag{display:none}.hero{padding:28px 16px 24px}.main{padding:20px 16px 50px}.card-grid{grid-template-columns:1fr}}"""

JS = """function switchTab(btn){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const cat=btn.dataset.cat;
  document.querySelectorAll('.section').forEach(sec=>{
    if(cat==='all')sec.classList.add('visible');
    else sec.classList.toggle('visible',sec.dataset.cat===cat);
  });
}
const obs=new IntersectionObserver(e=>e.forEach(x=>{if(x.isIntersecting){x.target.style.opacity='1';x.target.style.transform='translateY(0)'}}),{threshold:.05});
document.querySelectorAll('.card').forEach(c=>{c.style.opacity='0';c.style.transform='translateY(16px)';c.style.transition='opacity .4s,transform .4s,background .2s';obs.observe(c)});"""

def generate_html(all_videos, report_date):
    by_cat = {k:[] for k in CAT}
    for v,ch in all_videos:
        by_cat.setdefault(ch.get("category","general"),[]).append((v,ch))
    total  = len(all_videos)
    counts = {k:len(v) for k,v in by_cat.items()}
    gt     = datetime.now().strftime("%Y-%m-%d %H:%M")
    wdays  = ["週一","週二","週三","週四","週五","週六","週日"]
    dt     = datetime.strptime(report_date,"%Y-%m-%d")
    ddisp  = f"{dt.year} 年 {dt.month} 月 {dt.day} 日（{wdays[dt.weekday()]}）"
    secs   = "".join(section_html(c,by_cat[c]) for c in ["macro","crypto","etf","general"])
    return (
        f'<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8"/>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1.0"/>'
        f'<title>每日財經情報 — {report_date}</title>'
        f'<style>{CSS}</style></head><body>'
        f'<header class="site-header"><div class="header-inner">'
        f'<div class="logo-block"><div class="logo-icon">📈</div>'
        f'<div class="logo-text">每日<span>財經</span>情報</div></div>'
        f'<div style="display:flex;align-items:center;gap:16px">'
        f'<div class="date-badge">📅 {ddisp}</div>'
        f'<div class="update-tag">✦ 自動生成 {gt}</div>'
        f'</div></div></header>'
        f'<section class="hero"><div class="hero-inner">'
        f'<h1>今日 <span class="a">財經情報</span> 彙整</h1>'
        f'<p class="hero-sub">從 {len(CHANNELS)} 個精選 YouTube 頻道（美國+日本）自動抓取 · Claude AI 翻譯摘要</p>'
        f'<div class="stats-row">'
        f'<div class="stat-chip"><div class="dot da"></div><span class="num">{total}</span><span class="lbl">今日影片</span></div>'
        f'<div class="stat-chip"><div class="dot dm"></div><span class="num">{counts["macro"]}</span><span class="lbl">宏觀</span></div>'
        f'<div class="stat-chip"><div class="dot dc"></div><span class="num">{counts["crypto"]}</span><span class="lbl">加密</span></div>'
        f'<div class="stat-chip"><div class="dot de"></div><span class="num">{counts["etf"]}</span><span class="lbl">ETF</span></div>'
        f'<div class="stat-chip"><div class="dot dg"></div><span class="num">{counts["general"]}</span><span class="lbl">綜合</span></div>'
        f'</div></div></section>'
        f'<nav class="tab-nav"><ul class="tab-list">'
        f'<li><button class="tab-btn active" data-cat="all" onclick="switchTab(this)">全部 <span class="tab-count">{total}</span></button></li>'
        f'<li><button class="tab-btn" data-cat="macro" onclick="switchTab(this)">🌐 宏觀 <span class="tab-count">{counts["macro"]}</span></button></li>'
        f'<li><button class="tab-btn" data-cat="crypto" onclick="switchTab(this)">₿ 數字貨幣 <span class="tab-count">{counts["crypto"]}</span></button></li>'
        f'<li><button class="tab-btn" data-cat="etf" onclick="switchTab(this)">📊 ETF <span class="tab-count">{counts["etf"]}</span></button></li>'
        f'<li><button class="tab-btn" data-cat="general" onclick="switchTab(this)">💼 綜合 <span class="tab-count">{counts["general"]}</span></button></li>'
        f'</ul></nav>'
        f'<main class="main">{secs}</main>'
        f'<footer class="site-footer"><div class="footer-inner">'
        f'<p>📺 Bloomberg · CNBC · Coin Bureau · Real Vision · Kitco · Wealthion · Lyn Alden · InvestAnswers · 高橋ダン · 両学長 · 上念司 · テスタ · 投資の達人</p>'
        f'<p>🤖 Claude {CLAUDE_MODEL} 自動翻譯摘要 · {gt}</p>'
        f'<p>⚠ 本報告僅供資訊參考，不構成投資建議。</p>'
        f'</div></footer>'
        f'<script>{JS}</script></body></html>'
    )

# ── Main ─────────────────────────────────────────────────────────────
def main():
    log.info("="*55)
    log.info("  YouTube 財經日報自動化系統 啟動")
    log.info("="*55)
    log.info(f"YouTube API Key : {'✅ 已載入（'+YOUTUBE_API_KEY[:8]+'...）' if YOUTUBE_API_KEY else '❌ 未設定'}")
    log.info(f"Anthropic Key   : {'✅ 已載入（'+ANTHROPIC_API_KEY[:12]+'...）' if ANTHROPIC_API_KEY else '❌ 未設定'}")
    log.info(f"抓取時間範圍    : 最近 {FETCH_HOURS} 小時")

    # 測試 Anthropic API 是否可用
    ai_ok = False
    if ANTHROPIC_API_KEY:
        log.info("🔍 測試 Anthropic API 連線...")
        ai_ok = test_anthropic_key()
    else:
        log.warning("⚠ 未設定 ANTHROPIC_API_KEY，將跳過 AI 翻譯摘要")

    ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if (ANTHROPIC_API_KEY and ai_ok) else None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / f"{report_date}_finance_report.html"
    log.info(f"輸出路徑        : {output_path}")
    log.info("-"*55)

    all_videos = []
    for ch in CHANNELS:
        log.info(f"⏳ 抓取：{ch['name']} ...")
        videos = fetch_channel(ch)
        if not videos:
            log.info("   → 無新影片")
            continue
        for video in videos:
            if ai_client:
                log.info(f"   🤖 AI處理：{video['title'][:50]}...")
                video = ai_process(video, ch["lang"], ch["category"], ai_client)
            else:
                _set_fallback(video)
            all_videos.append((video, ch))

    log.info("-"*55)
    log.info(f"✅ 共抓取 {len(all_videos)} 部影片")
    if not all_videos:
        log.warning("今日無新影片，仍生成空白報告")
    html = generate_html(all_videos, report_date)
    output_path.write_text(html, encoding="utf