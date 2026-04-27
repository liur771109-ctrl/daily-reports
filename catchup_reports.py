#!/usr/bin/env python3
"""Catch-up Report Generator
Generates finance + AI reports for the past N days (default 7).
Each report covers a 24-hour window for that specific day.
Run once to backfill historical reports, then push to GitHub.
"""

import os, sys, json, logging, re, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone, date
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

# ── Config ────────────────────────────────────────────────────────────
YOUTUBE_API_KEY   = os.getenv("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUT_DIR        = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).parent)))
MAX_VIDEOS        = 3      # 每頻道最多取幾部
CATCHUP_DAYS      = 7      # 補幾天（不含今天）
CLAUDE_MODEL      = "claude-sonnet-4-6"
YT_API_BASE       = "https://www.googleapis.com/youtube/v3"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Finance Channels ─────────────────────────────────────────────────
FINANCE_CHANNELS = [
    {"id": "UCrM7B7SL_g1edFOnmj-SDKg", "handle": "BloombergMarketsandFinance", "name": "Bloomberg Markets", "lang": "en", "category": "macro"},
    {"id": "UCvJJ_dzjViJCoLf5uKUTwoA",  "handle": "CNBC",                       "name": "CNBC",             "lang": "en", "category": "macro"},
    {"id": "UCqK_GSMbpiV8spgD3ZGloLA",  "handle": "CoinBureau",                 "name": "Coin Bureau",      "lang": "en", "category": "crypto"},
    {"id": "UCXEqan5R9_3JlKCqSlXCYMg",  "handle": "realvision",                 "name": "Real Vision",      "lang": "en", "category": "macro"},
    {"id": "UCFRbT6FKe4YUGqD5-O2gy_w",  "handle": "KitcoNews",                  "name": "Kitco News",       "lang": "en", "category": "macro"},
    {"id": "UCFk9ZMHzDVgAGn0Y_4kFiYg",  "handle": "Wealthion",                  "name": "Wealthion",        "lang": "en", "category": "macro"},
    {"id": "UCQxOtDzLjKFb6NxRRJFN1UA",  "handle": "LynAldenInvestmentStrategy", "name": "Lyn Alden",        "lang": "en", "category": "macro"},
    {"id": "UCnzCBPOOfBMEf_4UoiKrHhQ",  "handle": "InvestAnswers",              "name": "InvestAnswers",    "lang": "en", "category": "crypto"},
    {"id": "UC7sg-8-SVQXZ3HMI9bTrZtQ",  "handle": "DanTakahashi17",             "name": "高橋ダン",          "lang": "ja", "category": "macro"},
    {"id": "UC5oGMJaEpKR_ZKYQk_b7XHZA", "handle": "ryogakucho",                "name": "両学長",            "lang": "ja", "category": "etf"},
]

# ── AI Channels ───────────────────────────────────────────────────────
AI_CHANNELS = [
    {"id": "",  "handle": "AnthropicAI",             "name": "Anthropic",             "lang": "en", "category": "claude"},
    {"id": "",  "handle": "samwitteveenai",           "name": "Sam Witteveen",         "lang": "en", "category": "claude"},
    {"id": "UC295-Dw4tzbADSmDecgwBuw", "handle": "GoogleforDevelopers", "name": "Google for Developers", "lang": "en", "category": "gemini"},
    {"id": "UCP4bf6IHJJQehibu6ai__cg", "handle": "GoogleDeepMind",      "name": "Google DeepMind",       "lang": "en", "category": "gemini"},
    {"id": "UCsBjURrPoezykLs9EqgamOA", "handle": "Fireship",            "name": "Fireship",              "lang": "en", "category": "aiapps"},
    {"id": "",  "handle": "matthew_berman",           "name": "Matthew Berman",        "lang": "en", "category": "industry"},
    {"id": "",  "handle": "TheAIAdvantage",           "name": "The AI Advantage",      "lang": "en", "category": "aiapps"},
    {"id": "",  "handle": "mreflow",                  "name": "Matt Wolfe",            "lang": "en", "category": "industry"},
    {"id": "",  "handle": "LexFridman",               "name": "Lex Fridman",           "lang": "en", "category": "industry"},
    {"id": "",  "handle": "guizang",                  "name": "歸藏",                   "lang": "zh", "category": "aiapps"},
    {"id": "",  "handle": "jiqizhixin",               "name": "機器之心",                "lang": "zh", "category": "industry"},
]

# ── YouTube API ───────────────────────────────────────────────────────
def yt_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    url = YT_API_BASE + "/" + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning("YT API: " + str(e))
        return {}

def fetch_day_api(channel_id, channel_name, day_start, day_end):
    """Fetch videos published on a specific day via YouTube Data API."""
    if not (YOUTUBE_API_KEY and channel_id):
        return []
    after  = day_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    before = day_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = yt_get("search", {
        "part": "snippet", "channelId": channel_id,
        "publishedAfter": after, "publishedBefore": before,
        "order": "date", "type": "video", "maxResults": MAX_VIDEOS
    })
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
    return videos

def fetch_day_ytdlp(handle, channel_name, target_date_str):
    """Fetch videos uploaded on a specific date via yt-dlp."""
    if not YTDLP_AVAILABLE or not handle:
        return []
    url = "https://www.youtube.com/@" + handle + "/videos"
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": "in_playlist",
                                "playlistend": 10, "skip_download": True}) as ydl:
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
            if detail.get("upload_date", "") != target_date_str:
                continue
            videos.append({
                "video_id": vid,
                "url": "https://www.youtube.com/watch?v=" + vid,
                "title": detail.get("title", ""),
                "description": (detail.get("description") or "")[:800],
                "published": detail.get("upload_date", ""),
                "channel": channel_name,
                "view_count": detail.get("view_count", 0) or 0,
            })
            if len(videos) >= MAX_VIDEOS:
                break
        return videos
    except Exception as e:
        log.warning("[yt-dlp] " + channel_name + ": " + str(e))
        return []

def fetch_channel_day(ch, day_start, day_end, target_date_str):
    cid, name, handle = ch.get("id", ""), ch["name"], ch.get("handle", "")
    videos = fetch_day_api(cid, name, day_start, day_end)
    if not videos and handle:
        videos = fetch_day_ytdlp(handle, name, target_date_str)
    return videos or []

# ── Claude AI ─────────────────────────────────────────────────────────
def _set_fallback(video):
    video.setdefault("title_zh", video["title"])
    desc = video.get("description", "").strip()
    video.setdefault("summary", (desc[:200] + "...") if len(desc) > 200 else desc or "(no description)")
    video.setdefault("tags", [])

def ai_process(video, lang, category, client, report_type):
    if report_type == "finance":
        cat_map = {"macro":"宏觀經濟","crypto":"數字貨幣","etf":"ETF","general":"綜合財經"}
        system_role = "你是專業財經分析師，專注宏觀經濟、加密貨幣、ETF 領域。"
    else:
        cat_map = {"claude":"Claude 動態","gemini":"Gemini 動態",
                   "aiapps":"AI 應用實戰","industry":"AI 行業快訊"}
        system_role = "你是專業 AI 技術分析師，專注 Claude、Gemini、LLM 應用領域。"
    cat_zh = cat_map.get(category, "財經/AI 技術")
    if lang == "zh":
        lang_desc = "中文（無需翻譯標題）"
        title_note = "繁體中文標題（原標題已是中文，適度潤色）"
    elif lang == "ja":
        lang_desc = "日文"
        title_note = "繁體中文標題（從日文翻譯）"
    else:
        lang_desc = "英文"
        title_note = "繁體中文標題（從英文翻譯，保留技術術語英文縮寫）"
    prompt = (
        system_role + "請處理以下 YouTube 影片資訊。\n\n"
        "影片語言：" + lang_desc + "\n"
        "類別：" + cat_zh + "\n"
        "頻道：" + video["channel"] + "\n"
        "標題：" + video["title"] + "\n"
        "描述：" + video.get("description", "（無）")[:400] + "\n\n"
        "請以 JSON 回覆：\n"
        "{\"title_zh\":\"" + title_note + "\","
        "\"summary\":\"核心摘要（繁體中文，120-160字）\","
        "\"tags\":[\"標籤1\",\"標籤2\",\"標籤3\"]}\n"
        "只回覆 JSON。"
    )
    try:
        msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=500,
                                     messages=[{"role": "user", "content": prompt}])
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            r = json.loads(m.group())
            video["title_zh"] = r.get("title_zh", video["title"])
            video["summary"]  = r.get("summary", "")
            video["tags"]     = r.get("tags", [])[:4]
            log.info("      ✅ " + video["title_zh"][:35] + "...")
        else:
            _set_fallback(video)
    except Exception as e:
        log.warning("      AI failed: " + str(e))
        _set_fallback(video)
    return video

# ── HTML (reuse from main scripts via import, or inline minimal) ──────
def fmt_views(n):
    if n >= 10000: return str(round(n/10000,1)) + "萬"
    if n >= 1000:  return str(round(n/1000,1)) + "K"
    return str(n) if n else "—"

def time_ago(pub):
    try:
        if "T" in str(pub):
            dt = datetime.fromisoformat(str(pub).replace("Z","+00:00"))
        else:
            dt = datetime.strptime(str(pub),"%Y%m%d").replace(tzinfo=timezone.utc)
        h = int((datetime.now(timezone.utc)-dt).total_seconds()/3600)
        if h < 1:  return "剛剛"
        if h < 24: return str(h) + "小時前"
        return str(h//24) + "天前"
    except Exception:
        return str(pub)

def build_report_html(all_videos, report_date, report_type):
    """Build HTML by importing and calling generate_html from the main scripts."""
    if report_type == "finance":
        import daily_finance_report as dr
        return dr.generate_html(all_videos, report_date)
    else:
        import daily_ai_report as dr
        return dr.generate_html(all_videos, report_date)

# ── Main ──────────────────────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("  補充歷史報告（過去 " + str(CATCHUP_DAYS) + " 天）")
    log.info("=" * 55)

    if not YOUTUBE_API_KEY:
        log.error("YOUTUBE_API_KEY 未設定，無法抓取歷史資料（yt-dlp 日期過濾效率低）")
        sys.exit(1)

    ai_client = None
    if ANTHROPIC_API_KEY:
        try:
            ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            test = ai_client.messages.create(model=CLAUDE_MODEL, max_tokens=10,
                                             messages=[{"role":"user","content":"Hi"}])
            log.info("✅ Anthropic API OK")
        except Exception as e:
            log.warning("⚠ Anthropic API 失敗，將跳過 AI 摘要：" + str(e))
            ai_client = None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date()

    for days_ago in range(1, CATCHUP_DAYS + 1):
        target = today - timedelta(days=days_ago)
        date_str     = target.strftime("%Y-%m-%d")
        date_str_ydl = target.strftime("%Y%m%d")

        # UTC day window
        day_start = datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=timezone.utc)
        day_end   = day_start + timedelta(days=1)

        log.info("")
        log.info("📅 處理：" + date_str)

        for report_type, channels in [("finance", FINANCE_CHANNELS), ("ai", AI_CHANNELS)]:
            out_path = OUTPUT_DIR / (date_str + "_" + report_type + "_report.html")
            if out_path.exists():
                log.info("   [" + report_type + "] 已存在，跳過")
                continue

            log.info("   [" + report_type + "] 抓取中...")
            all_videos = []
            for ch in channels:
                videos = fetch_channel_day(ch, day_start, day_end, date_str_ydl)
                if not videos:
                    continue
                for video in videos:
                    if ai_client:
                        video = ai_process(video, ch["lang"], ch["category"],
                                           ai_client, report_type)
                    else:
                        _set_fallback(video)
                    all_videos.append((video, ch))

            log.info("   [" + report_type + "] " + str(len(all_videos)) + " 部影片")

            try:
                html = build_report_html(all_videos, date_str, report_type)
                out_path.write_text(html, encoding="utf-8")
                log.info("   [" + report_type + "] ✅ 已儲存：" + out_path.name)
            except Exception as e:
                log.error("   [" + report_type + "] HTML 生成失敗：" + str(e))

    # Rebuild index
    log.info("")
    log.info("🔄 重建 index.html...")
    try:
        import build_index
        import importlib
        importlib.reload(build_index)
        log.info("✅ index.html 已更新")
    except Exception as e:
        log.warning("index.html 重建失敗（請手動執行 python build_index.py）：" + str(e))

    log.info("")
    log.info("=" * 55)
    log.info("✅ 補檔完成！請執行以下指令推送到 GitHub：")
    log.info("   git add -A")
    log.info("   git commit -m \"Add historical reports (past 7 days)\"")
    log.info("   git push")
    log.info("=" * 55)

if __name__ == "__main__":
    main()
