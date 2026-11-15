import os
import re
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# توقيت المدينة المنورة (UTC+3)
AST_TZ = timezone(timedelta(hours=3))

# إحداثيات القبر الدقيقة داخل مقبرة البقيع
LAT_LON = "24.466694,39.614944"

# النطاقات الزمنية
SQUARE_START_ISO = "2025-08-04T00:00:00Z"
SQUARE_END_ISO = "2025-08-09T23:59:59Z"
END_DATE_ISO = "2025-08-28T23:59:59Z"

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# 1. مصفوفة اللغات الشاملة (12 مجموعة لغوية لزوار المدينة المنورة)
BURIAL_QUERIES = {
    "Arabic": [
        "دفن في البقيع", "مقبرة البقيع دفن", "جنازة البقيع", "بقيع الغرقد دفن",
        "البقيع بعد الفجر", "دفن موتى البقيع", "البقيع 11 صفر", "البقيع 12 صفر",
        "البقيع 5 أغسطس", "البقيع 6 أغسطس", "قبور البقيع", "دفن ميت في البقيع"
    ],
    "Indonesian_Malay": [
        "pemakaman baqi", "pemakaman di baqi madinah", "makam baqi", "kuburan baqi",
        "jannatul baqi pemakaman", "penguburan baqi", "jenazah di baqi",
        "baqi 5 agustus 2025", "pengebumian baqi"
    ],
    "Urdu_Hindi": [
        "جنت البقیع تدفین", "جنت البقیع قبرستان", "بقیع میں تدفین", "جنت البقیع جنازہ",
        "jannatul baqi burial", "jannat ul baqi qabristan", "baqi madinah janaza",
        "baqi mein tadfeen"
    ],
    "Turkish": [
        "cennetül baki defin", "baki mezarlığı cenaze", "medine baki kabristanı",
        "cennetül baki cenaze", "baki mezarlığı defin"
    ],
    "Russian": [
        "кладбище баки похороны", "джаннат аль баки", "похороны в медина баки",
        "кладбище аль баки медина", "баки медина"
    ],
    "Central_Asia_Uzbek_Kazakh_Tajik": [
        "baqi qabristoni", "jannatul baqi dafn", "madina baqi qabristoni",
        "бақи зираты", "мадина бақи", "қабристони бақеъ"
    ],
    "Bengali": [
        "জান্নাতুল বাকি দাফন", "মদিনা জান্নাতুল বাকি", "জান্নাতুল বাকি কবরস্থান",
        "জান্নাতুল বাকিতে দাফন"
    ],
    "Persian_Dari": [
        "دفن در بقیع", "قبرستان بقیع تدفین", "جنت البقیع مدینه", "مراسم دفن بقیع"
    ],
    "Pashto": [
        "جنت البقيع خښول", "جنت البقيع هديره", "مدينه بقيع"
    ],
    "English": [
        "jannatul baqi burial", "al baqi cemetery burial", "burying in baqi madinah",
        "funeral in jannatul baqi", "baqi graveyard madinah"
    ],
    "French_North_West_Africa": [
        "enterrement baqi médine", "cimetière al baqi", "inhumation baqi",
        "jannatul baqi médine"
    ],
    "African_Hausa_Swahili": [
        "makabidhiano baqi", "makaburi ya baqi madina", "makabarta baqi madina"
    ]
}

# 2. كلمات عامة لمسح أيام المربع (4 إلى 8 أغسطس) وللمنصات النادرة
CORE_BAQI_TERMS = [
    "مقبرة البقيع", "بقيع الغرقد", "البقيع", "jannatul baqi", "pemakaman baqi",
    "جنت البقیع", "cennetül baki", "кладбище баки", "baqi qabristoni", "জান্নাতুল বাকি"
]

# 3. تقسيم المنصات بشكل معزول تماماً لمنع طغيان منصة على أخرى
ISOLATED_PLATFORMS = {
    "Snapchat": 'site:snapchat.com/spotlight OR site:snapchat.com/p OR site:story.snapchat.com',
    "VK_OK": 'site:vk.com/video OR site:vk.com/clip OR site:vk.com/wall OR site:ok.ru/video',
    "Telegram": 'site:t.me/s/',
    "X": 'site:x.com OR site:twitter.com',
    "ShortVideo_Other": 'site:likee.video OR site:kwai.com OR site:threads.net OR site:dailymotion.com/video',
    "TikTok": 'site:tiktok.com',
    "Instagram": 'site:instagram.com/reel OR site:instagram.com/p',
    "Facebook": 'site:facebook.com/reel OR site:facebook.com/watch OR site:facebook.com/*/videos'
}

results_db = {}

def load_previous_results():
    """تحميل النتائج السابقة للحفاظ عليها وتمييز النتائج الجديدة"""
    if os.path.exists("results.json"):
        try:
            with open("results.json", "r", encoding="utf-8") as f:
                old_list = json.load(f)
                for item in old_list:
                    item["is_new"] = False
                    results_db[item["url"]] = item
            print(f"[*] تم تحميل {len(results_db)} نتيجة سابقة من الذاكرة التراكمية.")
        except Exception as e:
            print(f"[!] تعذر قراءة النتائج السابقة: {e}")

def decode_tiktok_timestamp(url):
    """استخراج وقت الرفع الدقيق بالثانية من معرف فيديو تيك توك"""
    match = re.search(r"/video/(\d{19})", url)
    if match:
        vid_id = int(match.group(1))
        unix_ts = vid_id >> 32
        dt = datetime.fromtimestamp(unix_ts, tz=AST_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S (توقيت المدينة)"), unix_ts
    return None, 0

def detect_platform_name(url):
    u = url.lower()
    if "tiktok.com" in u: return "TikTok"
    if "youtube.com" in u or "youtu.be" in u: return "YouTube"
    if "instagram.com" in u: return "Instagram"
    if "facebook.com" in u or "fb.watch" in u: return "Facebook"
    if "snapchat.com" in u: return "Snapchat"
    if "vk.com" in u: return "VK"
    if "ok.ru" in u: return "OK.ru"
    if "t.me/" in u: return "Telegram"
    if "x.com" in u or "twitter.com" in u: return "X"
    if "likee.video" in u: return "Likee"
    if "kwai.com" in u: return "Kwai"
    if "threads.net" in u: return "Threads"
    if "dailymotion.com" in u: return "Dailymotion"
    return "Other"

def classify_tier(date_text, unix_ts=0):
    """تصنيف الأولوية الزمنية (1: يوم الدفن 5 أغسطس | 2: نفس المربع 4 أو 6-8 أغسطس | 3: رفع متأخر)"""
    if unix_ts > 0:
        if 1754355600 <= unix_ts <= 1754427599:
            return 1
        if 1754254800 <= unix_ts <= 1754686799:
            return 2
        return 3

    d_str = str(date_text)
    if any(x in d_str for x in ["2025-08-05", "5 Aug 2025", "Aug 5, 2025", "5 أغسطس"]):
        return 1
    if any(x in d_str for x in ["2025-08-04", "2025-08-06", "2025-08-07", "2025-08-08", "Aug 4, 2025", "Aug 6, 2025", "Aug 7, 2025", "Aug 8, 2025"]):
        return 2
    return 3

def add_result(url, title, platform, lang, published_at, thumbnail="", snippet="", tier=3):
    clean_url = url.split("?")[0] if "tiktok.com" in url or "instagram.com" in url else url
    if clean_url in results_db:
        if tier < results_db[clean_url].get("tier", 3):
            results_db[clean_url]["tier"] = tier
        if thumbnail and not results_db[clean_url].get("thumbnail"):
            results_db[clean_url]["thumbnail"] = thumbnail
        return

    results_db[clean_url] = {
        "url": clean_url,
        "title": title or "بدون عنوان",
        "platform": platform,
        "lang": lang,
        "published_at": published_at,
        "thumbnail": thumbnail,
        "snippet": snippet or "",
        "tier": tier,
        "is_new": True
    }

def search_youtube_geo():
    """1. رادار يوتيوب الجغرافي مع سحب الصفحات المتتالية (Pagination)"""
    if not YOUTUBE_API_KEY:
        return
    print("[*] 1/5 جاري مسح يوتيوب بالإحداثيات الجغرافية الدقيقة (مع سحب الصفحات)...")
    for radius in ["300m", "800m", "2000m"]:
        page_token = None
        for _ in range(3):  # سحب حتى 150 فيديو لكل نطاق جغرافي
            params = {
                "part": "snippet",
                "type": "video",
                "location": LAT_LON,
                "locationRadius": radius,
                "publishedAfter": SQUARE_START_ISO,
                "publishedBefore": END_DATE_ISO,
                "maxResults": 50,
                "order": "date",
                "key": YOUTUBE_API_KEY
            }
            if page_token:
                params["pageToken"] = page_token
            res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
            if res.status_code != 200:
                break
            data = res.json()
            for item in data.get("items", []):
                vid_id = item["id"]["videoId"]
                snip = item["snippet"]
                url = f"https://www.youtube.com/watch?v={vid_id}"
                pub = snip.get("publishedAt", "")
                thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                add_result(url, snip.get("title"), "YouTube", f"إحداثيات ({radius})", pub, thumb, snip.get("description", ""), classify_tier(pub))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(0.3)

def search_youtube_keywords():
    """2. مسح يوتيوب الشامل بـ 12 لغة + نافذة المربع"""
    if not YOUTUBE_API_KEY:
        return
    print("[*] 2/5 جاري مسح يوتيوب بـ 12 مجموعة لغوية...")
    for lang, keywords in BURIAL_QUERIES.items():
        for kw in keywords:
            params = {
                "part": "snippet",
                "type": "video",
                "q": kw,
                "publishedAfter": SQUARE_START_ISO,
                "publishedBefore": END_DATE_ISO,
                "maxResults": 50,
                "order": "date",
                "key": YOUTUBE_API_KEY
            }
            res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
            if res.status_code == 200:
                for item in res.json().get("items", []):
                    vid_id = item["id"]["videoId"]
                    snip = item["snippet"]
                    url = f"https://www.youtube.com/watch?v={vid_id}"
                    pub = snip.get("publishedAt", "")
                    thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                    add_result(url, snip.get("title"), "YouTube", lang, pub, thumb, snip.get("description", ""), classify_tier(pub))
            time.sleep(0.2)

    for kw in CORE_BAQI_TERMS:
        params = {
            "part": "snippet",
            "type": "video",
            "q": kw,
            "publishedAfter": SQUARE_START_ISO,
            "publishedBefore": SQUARE_END_ISO,
            "maxResults": 50,
            "order": "date",
            "key": YOUTUBE_API_KEY
        }
        res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
        if res.status_code == 200:
            for item in res.json().get("items", []):
                vid_id = item["id"]["videoId"]
                snip = item["snippet"]
                url = f"https://www.youtube.com/watch?v={vid_id}"
                pub = snip.get("publishedAt", "")
                thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                add_result(url, snip.get("title"), "YouTube", "مسح المربع (4-8 أغسطس)", pub, thumb, snip.get("description", ""), classify_tier(pub))
        time.sleep(0.2)

def run_serper_web(dork_query, lang_label):
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = json.dumps({"q": dork_query, "num": 30})
    try:
        res = requests.post("https://google.serper.dev/search", headers=headers, data=payload, timeout=15)
        if res.status_code != 200:
            return
        for item in res.json().get("organic", []):
            link = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            date_str = item.get("date", "ضمن نطاق البحث")
            unix_ts = 0
            platform = detect_platform_name(link)

            if platform == "TikTok":
                tt_date, unix_ts = decode_tiktok_timestamp(link)
                if tt_date:
                    date_str = f"وقت الرفع الدقيق: {tt_date}"
                    if unix_ts < 1754254800:
                        continue

            tier = classify_tier(date_str + " " + snippet, unix_ts)
            add_result(link, title, platform, lang_label, date_str, "", snippet, tier)
    except Exception as e:
        print(f"[!] خطأ في طلب البحث: {e}")

def run_serper_videos(video_query, lang_label):
    """استخدام محرك Google Videos المباشر لجلب الفيديوهات مع صورها المصغرة من كافة المنصات"""
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = json.dumps({"q": video_query, "num": 30})
    try:
        res = requests.post("https://google.serper.dev/videos", headers=headers, data=payload, timeout=15)
        if res.status_code != 200:
            return
        for item in res.json().get("videos", []):
            link = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            date_str = item.get("date", "ضمن نطاق البحث")
            thumb = item.get("imageUrl", "")
            unix_ts = 0
            platform = detect_platform_name(link)

            if platform == "TikTok":
                tt_date, unix_ts = decode_tiktok_timestamp(link)
                if tt_date:
                    date_str = f"وقت الرفع الدقيق: {tt_date}"
                    if unix_ts < 1754254800:
                        continue

            tier = classify_tier(date_str + " " + title, unix_ts)
            add_result(link, title, platform, lang_label, date_str, thumb, snippet, tier)
    except Exception as e:
        print(f"[!] خطأ في طلب الفيديو: {e}")

def search_isolated_platforms():
    """3. المسح المعزول لكل منصة على حدة (Snapchat, VK, OK.ru, Telegram, X, Likee, Kwai)"""
    if not SERPER_API_KEY:
        return
    print("[*] 3/5 جاري المسح المستقل والمعزول لمنصات: Snapchat, VK, OK.ru, Telegram, X, Likee, Kwai...")

    # فحص المنصات التي كانت مظلومة في الجولة الأولى بشكل مستقل تماماً
    rare_platforms = ["Snapchat", "VK_OK", "Telegram", "X", "ShortVideo_Other"]
    for plat_key in rare_platforms:
        site_rule = ISOLATED_PLATFORMS[plat_key]
        for term in CORE_BAQI_TERMS:
            # بحث داخل نافذة أغسطس 2025
            dork_aug = f'({site_rule}) "{term}" after:2025-08-03 before:2025-09-01'
            run_serper_web(dork_aug, f"مسح مستقل ({plat_key})")
            time.sleep(0.25)

            # بحث مفتوح بالكلمات الدقيقة في المنصات النادرة لأن بعضها لا يؤرشف تاريخها في جوجل بدقة
            dork_general = f'({site_rule}) "{term}" "2025"'
            run_serper_web(dork_general, f"مسح شامل ({plat_key})")
            time.sleep(0.25)

    print("[*] 4/5 جاري مسح TikTok و Instagram و Facebook بشكل مفصول لكل لغة...")
    major_platforms = ["TikTok", "Instagram", "Facebook"]
    for plat_key in major_platforms:
        site_rule = ISOLATED_PLATFORMS[plat_key]
        # مسح أيام المربع 4-9 أغسطس لكل منصة على حدة
        for term in CORE_BAQI_TERMS:
            dork_sq = f'({site_rule}) "{term}" after:2025-08-04 before:2025-08-10'
            run_serper_web(dork_sq, f"مربع البقيع ({plat_key})")
            time.sleep(0.25)

    # مسح كلمات الدفن بـ 12 لغة عبر محرك الفيديوهات المصور ومحرك الويب
    print("[*] 5/5 جاري مسح محرك Google Videos المصور بـ 12 لغة...")
    for lang, keywords in BURIAL_QUERIES.items():
        for kw in keywords:
            v_query = f'"{kw}" after:2025-08-04 before:2025-08-28'
            run_serper_videos(v_query, lang)
            time.sleep(0.25)

def generate_html_report():
    """بناء لوحة نتائج احترافية مع عدادات لكل منصة، شريط بحث فوري، وشارة للجديد"""
    sorted_items = sorted(
        results_db.values(),
        key=lambda x: (x.get("tier", 3), not x.get("is_new", False), x.get("published_at", ""))
    )

    platform_counts = {}
    tier1_count = 0
    tier2_count = 0
    new_count = 0

    for item in sorted_items:
        p = item.get("platform", "Other")
        platform_counts[p] = platform_counts.get(p, 0) + 1
        if item.get("tier") == 1:
            tier1_count += 1
        elif item.get("tier") == 2:
            tier2_count += 1
        if item.get("is_new"):
            new_count += 1

    # إنشاء أزرار ديناميكية لكل منصة موجودة
    plat_buttons_html = ""
    for plat, count in sorted(platform_counts.items(), key=lambda x: -x[1]):
        plat_buttons_html += f'<button class="filter-btn" onclick="filterByPlatform(\'{plat}\', this)">{plat} ({count})</button>\n'

    cards_html = ""
    for item in sorted_items:
        tier = item.get("tier", 3)
        is_new = item.get("is_new", False)
        if tier == 1:
            tier_badge = '<span class="tier-badge t1">🟢 يوم الدفن (5 أغسطس)</span>'
            card_class = "card tier-1"
        elif tier == 2:
            tier_badge = '<span class="tier-badge t2">🟡 نفس المربع (4 أو 6-8 أغسطس)</span>'
            card_class = "card tier-2"
        else:
            tier_badge = '<span class="tier-badge t3">نافذة الرفع المتأخر</span>'
            card_class = "card tier-3"

        new_badge = '<span class="new-badge">🆕 جديد</span>' if is_new else ""

        thumb_html = (
            f'<img src="{item["thumbnail"]}" loading="lazy" alt="thumb">'
            if item.get("thumbnail")
            else f'<div class="no-thumb">{item["platform"]} — اضغط لفتح المقطع</div>'
        )

        search_text = f"{item['title']} {item['snippet']} {item['lang']} {item['platform']} {item['published_at']}".replace('"', '')

        cards_html += f"""
        <div class="{card_class}" data-tier="{tier}" data-platform="{item['platform']}" data-new="{str(is_new).lower()}" data-search="{search_text}">
            {thumb_html}
            <div class="card-body">
                <div class="tags">
                    {new_badge}
                    <span class="badge plat">{item['platform']}</span>
                    <span class="badge lang">{item['lang']}</span>
                    {tier_badge}
                </div>
                <h3><a href="{item['url']}" target="_blank" rel="noopener">{item['title']}</a></h3>
                <p class="date">{item['published_at']}</p>
                <p class="snippet">{item['snippet'][:180]}</p>
                <a class="open-btn" href="{item['url']}" target="_blank" rel="noopener">مشاهدة الفيديو ↗</a>
            </div>
        </div>
        """

    html_template = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>رادار تنقيب البقيع الشامل - 5 أغسطس 2025</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .header { max-width: 1280px; margin: 0 auto 20px; background: #1e293b; padding: 20px; border-radius: 14px; border: 1px solid #334155; }
        .stats-bar { display: flex; gap: 15px; flex-wrap: wrap; margin: 12px 0; padding: 12px; background: #0f172a; border-radius: 10px; font-size: 14px; }
        .search-box { width: 100%; padding: 12px 15px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; font-size: 15px; margin-top: 10px; box-sizing: border-box; }
        .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
        .filter-btn { background: #334155; color: #fff; border: none; padding: 8px 13px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 13px; transition: 0.15s; }
        .filter-btn.active, .filter-btn:hover { background: #2563eb; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 18px; max-width: 1280px; margin: 0 auto; }
        .card { background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; display: flex; flex-direction: column; }
        .tier-1 { border: 2px solid #22c55e; box-shadow: 0 0 15px rgba(34, 197, 94, 0.25); }
        .tier-2 { border: 2px solid #eab308; }
        .card img { width: 100%; height: 180px; object-fit: cover; background: #000; }
        .no-thumb { width: 100%; height: 110px; background: #090d16; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-weight: bold; font-size: 14px; }
        .card-body { padding: 15px; flex: 1; display: flex; flex-direction: column; }
        .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
        .badge { font-size: 11px; padding: 3px 8px; border-radius: 6px; color: white; }
        .plat { background: #475569; font-weight: bold; }
        .lang { background: #0284c7; }
        .new-badge { background: #ec4899; color: #fff; font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: bold; }
        .tier-badge { font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: bold; }
        .t1 { background: #16a34a; color: #fff; }
        .t2 { background: #ca8a04; color: #fff; }
        .t3 { background: #334155; color: #cbd5e1; }
        h3 { margin: 0 0 8px; font-size: 15px; line-height: 1.4; }
        h3 a { color: #38bdf8; text-decoration: none; }
        .date { font-size: 13px; color: #fde047; margin: 0 0 8px; font-weight: bold; }
        .snippet { font-size: 13px; color: #cbd5e1; margin: 0 0 15px; flex: 1; word-break: break-word; }
        .open-btn { text-align: center; background: #2563eb; color: white; text-decoration: none; padding: 9px; border-radius: 6px; font-size: 14px; font-weight: bold; }
        .open-btn:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <div class="header">
        <h2>رادار تنقيب البقيع الشامل (الثلاثاء 5 أغسطس 2025 / 11 صفر 1447 هـ)</h2>
        <div class="stats-bar">
            <span>📦 الإجمالي التراكمي: <strong>__TOTAL_COUNT__</strong></span>
            <span>🆕 مكتشف في هذه الجولة: <strong>__NEW_COUNT__</strong></span>
            <span>🟢 يوم الدفن (5 أغسطس): <strong>__TIER1_COUNT__</strong></span>
            <span>🟡 أيام المربع (4 و 6-8 أغسطس): <strong>__TIER2_COUNT__</strong></span>
        </div>
        <input type="text" id="searchInput" class="search-box" placeholder="🔍 ابحث فوراً داخل النتائج (مثال: فجر، جنازة، باقي، 5 أغسطس، اسم لغة أو كلمة)..." oninput="applySearch()">
        <div class="filters">
            <button class="filter-btn active" onclick="filterByMode('all', this)">عرض الكل (__TOTAL_COUNT__)</button>
            <button class="filter-btn" style="border:1px solid #ec4899" onclick="filterByMode('new', this)">🆕 الجديد فقط (__NEW_COUNT__)</button>
            <button class="filter-btn" style="border:1px solid #22c55e" onclick="filterByMode('tier-1', this)">🟢 يوم الدفن: 5 أغسطس (__TIER1_COUNT__)</button>
            <button class="filter-btn" style="border:1px solid #eab308" onclick="filterByMode('tier-2', this)">🟡 نفس المربع: 4 و 6-8 أغسطس (__TIER2_COUNT__)</button>
        </div>
        <div class="filters">
            __PLATFORM_BUTTONS__
        </div>
    </div>
    <div class="grid" id="cardsGrid">
        __CARDS_HTML__
    </div>
    <script>
        function setActiveBtn(btn) {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
        }
        function filterByMode(mode, btn) {
            setActiveBtn(btn);
            document.querySelectorAll('.card').forEach(card => {
                if (mode === 'all') card.style.display = 'flex';
                else if (mode === 'new') card.style.display = card.dataset.new === 'true' ? 'flex' : 'none';
                else if (mode === 'tier-1') card.style.display = card.dataset.tier === '1' ? 'flex' : 'none';
                else if (mode === 'tier-2') card.style.display = card.dataset.tier === '2' ? 'flex' : 'none';
            });
        }
        function filterByPlatform(plat, btn) {
            setActiveBtn(btn);
            document.querySelectorAll('.card').forEach(card => {
                card.style.display = card.dataset.platform === plat ? 'flex' : 'none';
            });
        }
        function applySearch() {
            const q = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.card').forEach(card => {
                const text = (card.dataset.search || '').toLowerCase();
                card.style.display = text.includes(q) ? 'flex' : 'none';
            });
        }
    </script>
</body>
</html>"""

    final_html = (
        html_template
        .replace("__TOTAL_COUNT__", str(len(results_db)))
        .replace("__NEW_COUNT__", str(new_count))
        .replace("__TIER1_COUNT__", str(tier1_count))
        .replace("__TIER2_COUNT__", str(tier2_count))
        .replace("__PLATFORM_BUTTONS__", plat_buttons_html)
        .replace("__CARDS_HTML__", cards_html)
    )

    with open("results.html", "w", encoding="utf-8") as f:
        f.write(final_html)
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(list(results_db.values()), f, ensure_ascii=False, indent=2)
    print(f"[+] اكتمل التحديث الشامل! الإجمالي الآن: {len(results_db)} نتيجة (منها {new_count} جديدة).")

if __name__ == "__main__":
    load_previous_results()
    search_youtube_geo()
    search_youtube_keywords()
    search_isolated_platforms()
    generate_html_report()
