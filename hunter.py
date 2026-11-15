import os
import re
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# توقيت المدينة المنورة (UTC+3)
AST_TZ = timezone(timedelta(hours=3))

# إحداثيات القبر الدقيقة داخل مقبرة البقيع
LAT = 24.466694
LON = 39.614944
LAT_LON = f"{LAT},{LON}"

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()

api_status = {
    "youtube": "محفوظ بالذاكرة + مصفاة ذكية",
    "serper": "متصل",
    "snapmap": "مكتمل"
}

ALL_PLATFORMS_ORDER = [
    "YouTube", "TikTok", "Snapchat", "Instagram", "Facebook",
    "VK", "Telegram", "X", "Dailymotion", "Likee_Kwai", "Other"
]

# الكلمات الدالة على مقبرة البقيع أو الدفن والجنائز بجميع اللغات
BAQI_POSITIVE_WORDS = [
    "بقيع", "البقيع", "الغرقد", "مقبر", "دفن", "جناز", "جنائز", "قبر", "قبور", "تشييع", "فجر",
    "baqi", "baki", "baqee", "buqee", "jannatul", "jannat ul", "cemetery", "graveyard", "burial", "funeral", "grave",
    "pemakaman", "makam", "kuburan", "penguburan", "jenazah", "pengebumian",
    "بقیع", "تدفین", "قبرستان", "جنازہ", "میت", "خښول", "هديره",
    "cennetül", "cennetul", "mezarlığı", "mezarligi", "kabristan", "defin", "cenaze",
    "баки", "бақи", "бақеъ", "кладбище", "похороны", "qabriston", "dafn", "зираты", "қабристони",
    "বাকি", "জান্নাতুল", "দাফন", "কবরস্থান",
    "enterrement", "cimetière", "inhumation", "makaburi", "makabarta"
]

# الكلمات الدالة على الضوضاء والمقاطع غير المرتبطة (أنمي Baki، ألعاب، طبخ، تسوق، إلخ)
NOISE_NEGATIVE_WORDS = [
    "hanma", "grappler", "yujiro", "anime", "manga", "netflix", "episode", "season", "fight", "gym", "workout",
    "gaming", "roblox", "pubg", "free fire", "minecraft", "fortnite", "edit", "amv",
    "recipe", "cooking", "food", "restaurant", "hotel review", "shopping", "mall", "price", "discount",
    "مسلسل", "حلقة", "فيلم", "أنمي", "انمي", "لعبة", "تحدي", "طبخ", "وصفة", "مطعم", "تسوق", "مول", "تفسير حلم", "تفسير الاحلام"
]

results_db = {}

def compute_relevance(item):
    """فحص ذكي لتحديد هل الفيديو مرتبط فعلياً بمقبرة البقيع/الدفن أم ضوضاء عشوائية"""
    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('lang', '')}".lower()

    # استبعاد فوري إذا كان يحتوي على كلمات الضوضاء (مثل أنمي Baki Hanma أو ألعاب أو طبخ)
    for nw in NOISE_NEGATIVE_WORDS:
        if nw in text:
            return "noise"

    # إذا كان يحتوي صراحة على كلمات البقيع أو الدفن أو الجنازة
    for pw in BAQI_POSITIVE_WORDS:
        if pw in text:
            return "strict"

    # الفيديوهات الملتقطة بالإحداثيات القريبة جداً (300m أو 500m) نعتبرها مرتبطة
    lang_tag = item.get("lang", "")
    if "300m" in lang_tag or "500m" in lang_tag:
        return "strict"

    return "noise"

def load_previous_results():
    """تحميل جميع النتائج السابقة وإعادة فحصها بالمصفاة الذكية"""
    if os.path.exists("results.json"):
        try:
            with open("results.json", "r", encoding="utf-8") as f:
                old_list = json.load(f)
                for item in old_list:
                    item["is_new"] = False
                    item["relevance"] = compute_relevance(item)
                    results_db[item["url"]] = item
            print(f"[*] تم تحميل وفحص {len(results_db)} نتيجة سابقة.")
        except Exception as e:
            print(f"[!] تنبيه عند قراءة الذاكرة السابقة: {e}")

def decode_tiktok_timestamp(url):
    match = re.search(r"/video/(\d{19})", url)
    if match:
        vid_id = int(match.group(1))
        unix_ts = vid_id >> 32
        dt = datetime.fromtimestamp(unix_ts, tz=AST_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S (توقيت المدينة)"), unix_ts
    return None, 0

def detect_platform_name(url):
    u = url.lower()
    if "tiktok.com" in u:
        return "TikTok"
    if "snapchat.com" in u:
        return "Snapchat"
    if "instagram.com" in u:
        return "Instagram"
    if "facebook.com" in u or "fb.watch" in u:
        return "Facebook"
    if "vk.com" in u or "ok.ru" in u or "vkvideo.ru" in u:
        return "VK"
    if "t.me/" in u or "telegram.me" in u or "telegram.org" in u:
        return "Telegram"
    if "x.com" in u or "twitter.com" in u:
        return "X"
    if "dailymotion.com" in u:
        return "Dailymotion"
    if any(k in u for k in ["likee.video", "kwai.com", "threads.net", "threads.com", "snackvideo.com", "sharechat.com", "mojapp.in"]):
        return "Likee_Kwai"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    return "Other"

def classify_tier(date_text, unix_ts=0):
    if unix_ts > 0:
        if 1754355600 <= unix_ts <= 1754427599:
            return 1
        if 1754254800 <= unix_ts <= 1754686799:
            return 2
        return 3

    d_str = str(date_text)
    if any(x in d_str for x in [
        "2025-08-05", "5 Aug 2025", "Aug 5, 2025", "5 أغسطس", "5 اغسطس",
        "05.08.2025", "05/08/2025", "5/8/2025", "11 صفر", "11/2/1447", "11/02/1447"
    ]):
        return 1
    if any(x in d_str for x in [
        "2025-08-04", "2025-08-06", "2025-08-07", "2025-08-08",
        "Aug 4, 2025", "Aug 6, 2025", "Aug 7, 2025", "Aug 8, 2025",
        "4 أغسطس", "6 أغسطس", "7 أغسطس", "8 أغسطس", "10 صفر", "12 صفر", "13 صفر"
    ]):
        return 2
    return 3

def add_result(url, title, platform, lang, published_at, thumbnail="", snippet="", tier=3):
    if not url:
        return
    clean_url = url.split("?")[0] if ("tiktok.com" in url or "instagram.com" in url) else url
    if clean_url in results_db:
        if tier < results_db[clean_url].get("tier", 3):
            results_db[clean_url]["tier"] = tier
        if thumbnail and not results_db[clean_url].get("thumbnail"):
            results_db[clean_url]["thumbnail"] = thumbnail
        results_db[clean_url]["relevance"] = compute_relevance(results_db[clean_url])
        return

    item = {
        "url": clean_url,
        "title": title or "مقطع فيديو مكتشف",
        "platform": platform,
        "lang": lang,
        "published_at": published_at,
        "thumbnail": thumbnail,
        "snippet": snippet or "",
        "tier": tier,
        "is_new": True
    }
    item["relevance"] = compute_relevance(item)
    results_db[clean_url] = item

def serper_request(query, label, endpoint="search", forced_platform=None):
    if not SERPER_API_KEY:
        return 0
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload_dict = {"q": query}

    count_added = 0
    try:
        res = requests.post(
            f"https://google.serper.dev/{endpoint}",
            headers=headers,
            json=payload_dict,
            timeout=15
        )
        if res.status_code == 200:
            api_status["serper"] = "✅ متصل (مصفاة الدقة العالية)"
            data = res.json()
            items = data.get("organic", []) if endpoint == "search" else data.get("videos", [])
            for item in items:
                link = item.get("link", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                date_str = item.get("date", "ضمن نتائج البحث")
                thumb = item.get("imageUrl", "")
                unix_ts = 0
                platform = forced_platform if forced_platform else detect_platform_name(link)

                if platform == "TikTok":
                    tt_date, unix_ts = decode_tiktok_timestamp(link)
                    if tt_date:
                        date_str = f"وقت الرفع الدقيق: {tt_date}"
                        if unix_ts < 1754000000:
                            continue

                tier = classify_tier(f"{date_str} {title} {snippet}", unix_ts)
                add_result(link, title, platform, label, date_str, thumb, snippet, tier)
                count_added += 1
    except Exception as e:
        print(f"[!] استثناء في اتصال Serper: {e}")
    return count_added

def search_ultra_specific_burial_scenes():
    """بحث شديد التخصص في مشاهد الدفن والقبور المفتوحة وحفر القبور في البقيع فقط"""
    if not SERPER_API_KEY:
        return
    print("[*] جاري البحث فائق الدقة في أوصاف مشاهد الدفن والقبور داخل البقيع...")
    ultra_queries = [
        "دفن ميت في البقيع بعد الفجر",
        "لحظة دفن في مقبرة البقيع",
        "تشييع جنازة في البقيع",
        "قبور البقيع من الداخل",
        "حفر القبور في البقيع",
        "صلاة الفجر والدفن في البقيع",
        "prosesi pemakaman di baqi madinah",
        "penguburan jenazah di jannatul baqi",
        "suasana pemakaman baqi subuh",
        "جنت البقیع میں تدفین کا منظر",
        "مدینہ جنت البقیع قبرستان تدفین",
        "cennetül baki cenaze defin",
        "medine baki mezarlığı defin",
        "похороны на кладбище баки в медине",
        "madina baqi qabristoni dafn marosimi",
        "জান্নাতুল বাকি কবরস্থানে দাফন"
    ]
    for uq in ultra_queries:
        serper_request(f"{uq} after:2025-08-04 before:2025-08-25", "تطابق المشهد الدقيق", endpoint="videos")
        time.sleep(0.12)
        serper_request(f"{uq} after:2025-08-04 before:2025-08-25", "تطابق المشهد الدقيق", endpoint="search")
        time.sleep(0.12)

def extract_embed_url(url, platform):
    """توليد رابط تشغيل مباشر داخل البطاقة بدون مغادرة الصفحة"""
    if platform == "YouTube":
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
        if m:
            return f"https://www.youtube.com/embed/{m.group(1)}?autoplay=1"
    elif platform == "TikTok":
        m = re.search(r"/video/(\d{19})", url)
        if m:
            return f"https://www.tiktok.com/embed/v2/{m.group(1)}"
    elif platform == "Dailymotion":
        m = re.search(r"/video/([a-zA-Z0-9]+)", url)
        if m:
            return f"https://www.dailymotion.com/embed/video/{m.group(1)}?autoplay=1"
    return ""

def generate_html_report():
    """بناء لوحة التحكم الذكية V6 مع مصفاة الضوضاء، المشغل الداخلي، وزر الحذف النهائي"""
    sorted_items = sorted(
        results_db.values(),
        key=lambda x: (
            x.get("relevance") != "strict",
            x.get("tier", 3),
            not x.get("is_new", False),
            x.get("published_at", "")
        )
    )

    platform_counts = {p: 0 for p in ALL_PLATFORMS_ORDER}
    strict_count = 0
    noise_count = 0
    tier1_strict_count = 0
    tier2_strict_count = 0
    new_count = 0

    for item in sorted_items:
        p = item.get("platform", "Other")
        rel = item.get("relevance", "strict")
        if rel == "strict":
            strict_count += 1
            platform_counts[p] = platform_counts.get(p, 0) + 1
            if item.get("tier") == 1:
                tier1_strict_count += 1
            elif item.get("tier") == 2:
                tier2_strict_count += 1
        else:
            noise_count += 1
        if item.get("is_new"):
            new_count += 1

    plat_buttons_html = f'<button class="filter-btn plat-btn active" onclick="setPlatformFilter(\'all\', this)">كل المنصات الصافية ({strict_count})</button>\n'
    for plat in ALL_PLATFORMS_ORDER:
        count = platform_counts.get(plat, 0)
        btn_style = 'style="border:1px solid #38bdf8;"' if count > 0 else 'style="opacity:0.6;"'
        plat_buttons_html += f'<button class="filter-btn plat-btn" {btn_style} onclick="setPlatformFilter(\'{plat}\', this)">{plat} ({count})</button>\n'

    cards_html = ""
    for idx, item in enumerate(sorted_items):
        tier = item.get("tier", 3)
        is_new = item.get("is_new", False)
        rel = item.get("relevance", "strict")
        url_safe = item["url"].replace('"', '&quot;')
        embed_url = extract_embed_url(item["url"], item["platform"])

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
            else f'<div class="no-thumb">{item["platform"]} — مقطع فيديو</div>'
        )

        play_here_btn = (
            f'<button class="play-btn" onclick="playInline({idx}, \'{embed_url}\', \'{url_safe}\')" title="تشغيل الفيديو هنا بدون مغادرة الصفحة">▶️ معاينة</button>'
            if embed_url else ""
        )

        search_text = f"{item['title']} {item['snippet']} {item['lang']} {item['platform']} {item['published_at']}".replace('"', '')

        cards_html += f"""
        <div class="{card_class}" id="card-{idx}" data-url="{url_safe}" data-tier="{tier}" data-platform="{item['platform']}" data-new="{str(is_new).lower()}" data-relevance="{rel}" data-search="{search_text}">
            <div class="media-box" id="media-{idx}">
                {thumb_html}
            </div>
            <div class="card-body">
                <div class="tags">
                    {new_badge}
                    <span class="badge plat">{item['platform']}</span>
                    <span class="badge lang">{item['lang']}</span>
                    {tier_badge}
                    <span class="seen-label" style="display:none;">✔️ شوهد</span>
                </div>
                <h3><a href="{url_safe}" target="_blank" rel="noopener" onclick="markAsSeen('{url_safe}')">{item['title']}</a></h3>
                <p class="date">{item['published_at']}</p>
                <p class="snippet">{item['snippet'][:170]}</p>
                <div class="card-actions">
                    <a class="open-btn" href="{url_safe}" target="_blank" rel="noopener" onclick="markAsSeen('{url_safe}')">فتح ↗</a>
                    {play_here_btn}
                    <button class="star-btn" onclick="toggleStar('{url_safe}', this)" title="إضافة للمفضلة">⭐</button>
                    <button class="seen-btn" onclick="toggleSeenManual('{url_safe}', this)" title="تحديد كمشاهد">👁️</button>
                    <button class="trash-btn" onclick="trashCard('{url_safe}')" title="استبعاد وإخفاء نهائياً لأنه غير مرتبط">🗑️</button>
                </div>
            </div>
        </div>
        """

    snap_map_url = f"https://map.snapchat.com/@{LAT},{LON},18.00z"

    html_template = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>رادار تنقيب البقيع الشامل V6 - المصفاة الذكية</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .header { max-width: 1280px; margin: 0 auto 20px; background: #1e293b; padding: 20px; border-radius: 14px; border: 1px solid #334155; }
        .stats-bar { display: flex; gap: 14px; flex-wrap: wrap; margin: 10px 0; padding: 12px; background: #0f172a; border-radius: 10px; font-size: 13.5px; align-items: center; }
        .api-bar { display: flex; gap: 12px; flex-wrap: wrap; margin: 8px 0; padding: 10px 14px; background: #172554; border: 1px solid #1d4ed8; border-radius: 10px; font-size: 13px; align-items: center; }
        .snap-btn { background: #eab308; color: #000; text-decoration: none; padding: 6px 12px; border-radius: 8px; font-weight: bold; font-size: 12.5px; }
        .backup-btn { background: #334155; color: #fff; border: 1px solid #64748b; padding: 6px 10px; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: bold; }
        .search-box { width: 100%; padding: 12px 15px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; font-size: 15px; margin-top: 8px; box-sizing: border-box; }
        .filter-group-title { font-size: 12px; color: #94a3b8; margin-top: 12px; margin-bottom: 5px; font-weight: bold; }
        .filters { display: flex; gap: 8px; flex-wrap: wrap; }
        .filter-btn { background: #334155; color: #fff; border: none; padding: 8px 13px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 13px; transition: 0.15s; }
        .filter-btn.active, .filter-btn:hover { background: #2563eb; opacity: 1 !important; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; max-width: 1280px; margin: 0 auto; }
        .card { background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; display: flex; flex-direction: column; transition: 0.2s; }
        .card.seen-card { opacity: 0.42; border-color: #475569 !important; box-shadow: none !important; }
        .card.starred-card { border: 2px solid #f59e0b !important; box-shadow: 0 0 18px rgba(245, 158, 11, 0.4) !important; opacity: 1 !important; }
        .tier-1 { border: 2px solid #22c55e; box-shadow: 0 0 15px rgba(34, 197, 94, 0.25); }
        .tier-2 { border: 2px solid #eab308; }
        .media-box { width: 100%; background: #000; position: relative; }
        .media-box img { width: 100%; height: 185px; object-fit: cover; display: block; }
        .media-box iframe { width: 100%; height: 260px; border: none; display: block; }
        .no-thumb { width: 100%; height: 110px; background: #090d16; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-weight: bold; font-size: 14px; }
        .card-body { padding: 14px; flex: 1; display: flex; flex-direction: column; }
        .tags { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 9px; }
        .badge { font-size: 11px; padding: 3px 7px; border-radius: 6px; color: white; }
        .plat { background: #475569; font-weight: bold; }
        .lang { background: #0284c7; }
        .new-badge { background: #ec4899; color: #fff; font-size: 11px; padding: 3px 7px; border-radius: 6px; font-weight: bold; }
        .seen-label { background: #64748b; color: #fff; font-size: 11px; padding: 3px 7px; border-radius: 6px; font-weight: bold; }
        .tier-badge { font-size: 11px; padding: 3px 7px; border-radius: 6px; font-weight: bold; }
        .t1 { background: #16a34a; color: #fff; }
        .t2 { background: #ca8a04; color: #fff; }
        .t3 { background: #334155; color: #cbd5e1; }
        h3 { margin: 0 0 7px; font-size: 14.5px; line-height: 1.4; }
        h3 a { color: #38bdf8; text-decoration: none; }
        .date { font-size: 12.5px; color: #fde047; margin: 0 0 7px; font-weight: bold; }
        .snippet { font-size: 12.5px; color: #cbd5e1; margin: 0 0 12px; flex: 1; word-break: break-word; }
        .card-actions { display: flex; gap: 6px; align-items: center; }
        .open-btn { flex: 1; text-align: center; background: #2563eb; color: white; text-decoration: none; padding: 8px; border-radius: 6px; font-size: 13px; font-weight: bold; }
        .play-btn { background: #059669; color: #fff; border: none; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 12.5px; font-weight: bold; }
        .star-btn, .seen-btn, .trash-btn { background: #334155; border: 1px solid #475569; color: #fff; padding: 7px 9px; border-radius: 6px; cursor: pointer; font-size: 13px; }
        .star-btn.active { background: #f59e0b; color: #000; border-color: #f59e0b; }
        .trash-btn:hover { background: #dc2626; border-color: #dc2626; }
    </style>
</head>
<body>
    <div class="header">
        <h2>رادار تنقيب البقيع الشامل V6 — المصفاة الذكية (الثلاثاء 5 أغسطس 2025 / 11 صفر 1447 هـ)</h2>
        <div class="api-bar">
            <span>🎯 الصافي المرتبط بالبقيع: <strong>__STRICT_COUNT__</strong></span>
            <span>🚫 ضوضاء تم عزلها تلقائياً: <strong>__NOISE_COUNT__</strong></span>
            <button class="backup-btn" onclick="exportProgress()">💾 نسخ سجل المشاهدة والمفضلة</button>
            <button class="backup-btn" onclick="importProgress()">📥 استعادة السجل</button>
            <a href="__SNAP_MAP_URL__" target="_blank" rel="noopener" class="snap-btn" style="margin-right:auto;">🗺️ خريطة السناب فوق القبر ↗</a>
        </div>
        <div class="stats-bar">
            <span>🟢 يوم الدفن الصافي (5 أغسطس): <strong>__TIER1_COUNT__</strong></span>
            <span>🟡 أيام المربع الصافي (4 و 6-8 أغسطس): <strong>__TIER2_COUNT__</strong></span>
            <span>👁️ شاهدته: <strong id="seenCounter">0</strong></span>
            <span>⭐ المفضلة: <strong id="starCounter">0</strong></span>
            <span>🗑️ استبعدته: <strong id="trashCounter">0</strong></span>
            <span>🔍 المعروض الآن: <strong id="visibleCounter">0</strong></span>
        </div>
        <input type="text" id="searchInput" class="search-box" placeholder="🔍 ابحث فوراً داخل النتائج (مثال: فجر، جنازة، دفن، قبر، اسم لغة أو كلمة)..." oninput="applyAllFilters()">
        
        <div class="filter-group-title">1️⃣ فلتر الدقة والأولوية الزمنية (الوضع الافتراضي يعرض الصافي المرتبط بالبقيع فقط ويعزل المقاطع العشوائية):</div>
        <div class="filters">
            <button class="filter-btn mode-btn active" onclick="setModeFilter('strict-all', this)">🎯 الصافي المؤكد للبقيع (__STRICT_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #22c55e" onclick="setModeFilter('tier-1', this)">🟢 يوم الدفن الصافي: 5 أغسطس (__TIER1_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #eab308" onclick="setModeFilter('tier-2', this)">🟡 نفس المربع الصافي: 4 و 6-8 أغسطس (__TIER2_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #38bdf8" onclick="setModeFilter('unseen', this)">🙈 الصافي الذي لم أشاهده بعد</button>
            <button class="filter-btn mode-btn" style="border:1px solid #f59e0b" onclick="setModeFilter('starred', this)">⭐ المفضلة والمشتبه به</button>
            <button class="filter-btn mode-btn" style="opacity:0.7" onclick="setModeFilter('raw-all', this)">📦 عرض كل الأرشيف بما فيه المعزول (__TOTAL_COUNT__)</button>
        </div>

        <div class="filter-group-title">2️⃣ فلتر المنصة (يتقاطع مع الفلتر العلوي):</div>
        <div class="filters">
            __PLATFORM_BUTTONS__
        </div>
    </div>
    <div class="grid" id="cardsGrid">
        __CARDS_HTML__
    </div>
    <script>
        let currentMode = 'strict-all';
        let currentPlatform = 'all';
        let seenSet = new Set(JSON.parse(localStorage.getItem('baqi_seen_urls') || '[]'));
        let starSet = new Set(JSON.parse(localStorage.getItem('baqi_star_urls') || '[]'));
        let trashSet = new Set(JSON.parse(localStorage.getItem('baqi_trash_urls') || '[]'));

        function saveStorage() {
            localStorage.setItem('baqi_seen_urls', JSON.stringify([...seenSet]));
            localStorage.setItem('baqi_star_urls', JSON.stringify([...starSet]));
            localStorage.setItem('baqi_trash_urls', JSON.stringify([...trashSet]));
            document.getElementById('seenCounter').textContent = seenSet.size;
            document.getElementById('starCounter').textContent = starSet.size;
            document.getElementById('trashCounter').textContent = trashSet.size;
        }

        function playInline(idx, embedUrl, rawUrl) {
            const box = document.getElementById('media-' + idx);
            if (box && embedUrl) {
                box.innerHTML = '<iframe src="' + embedUrl + '" allow="autoplay; encrypted-media" allowfullscreen></iframe>';
                markAsSeen(rawUrl);
            }
        }

        function syncCardStates() {
            document.querySelectorAll('.card').forEach(card => {
                const url = card.dataset.url;
                const seenLbl = card.querySelector('.seen-label');
                const starBtn = card.querySelector('.star-btn');
                if (seenSet.has(url)) {
                    card.classList.add('seen-card');
                    if (seenLbl) seenLbl.style.display = 'inline-block';
                } else {
                    card.classList.remove('seen-card');
                    if (seenLbl) seenLbl.style.display = 'none';
                }
                if (starSet.has(url)) {
                    card.classList.add('starred-card');
                    if (starBtn) starBtn.classList.add('active');
                } else {
                    card.classList.remove('starred-card');
                    if (starBtn) starBtn.classList.remove('active');
                }
            });
            saveStorage();
        }

        function markAsSeen(url) {
            seenSet.add(url);
            syncCardStates();
            if (currentMode === 'unseen') applyAllFilters();
        }

        function toggleSeenManual(url, btn) {
            if (seenSet.has(url)) seenSet.delete(url);
            else seenSet.add(url);
            syncCardStates();
            applyAllFilters();
        }

        function toggleStar(url, btn) {
            if (starSet.has(url)) starSet.delete(url);
            else starSet.add(url);
            syncCardStates();
            applyAllFilters();
        }

        function trashCard(url) {
            trashSet.add(url);
            saveStorage();
            applyAllFilters();
        }

        function exportProgress() {
            const data = JSON.stringify({
                seen: [...seenSet],
                star: [...starSet],
                trash: [...trashSet]
            });
            navigator.clipboard.writeText(data).then(() => {
                alert('تم نسخ سجل المشاهدة والمفضلة إلى الحافظة! يمكنك لصقه في أي جهاز آخر عبر زر استعادة السجل.');
            });
        }

        function importProgress() {
            const input = prompt('الصق كود السجل الذي نسخته هنا:');
            if (!input) return;
            try {
                const obj = JSON.parse(input);
                (obj.seen || []).forEach(u => seenSet.add(u));
                (obj.star || []).forEach(u => starSet.add(u));
                (obj.trash || []).forEach(u => trashSet.add(u));
                syncCardStates();
                applyAllFilters();
                alert('تم استعادة السجل بنجاح!');
            } catch (e) {
                alert('الكود غير صحيح.');
            }
        }

        function setModeFilter(mode, btn) {
            currentMode = mode;
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            applyAllFilters();
        }

        function setPlatformFilter(plat, btn) {
            currentPlatform = plat;
            document.querySelectorAll('.plat-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            applyAllFilters();
        }

        function applyAllFilters() {
            const q = document.getElementById('searchInput').value.toLowerCase().trim();
            let visible = 0;
            document.querySelectorAll('.card').forEach(card => {
                const url = card.dataset.url;
                if (trashSet.has(url) && currentMode !== 'starred') {
                    card.style.display = 'none';
                    return;
                }
                const tier = card.dataset.tier;
                const plat = card.dataset.platform;
                const rel = card.dataset.relevance;
                const text = (card.dataset.search || '').toLowerCase();

                let matchMode = true;
                if (currentMode === 'strict-all') matchMode = (rel === 'strict');
                else if (currentMode === 'tier-1') matchMode = (rel === 'strict' && tier === '1');
                else if (currentMode === 'tier-2') matchMode = (rel === 'strict' && tier === '2');
                else if (currentMode === 'unseen') matchMode = (rel === 'strict' && !seenSet.has(url));
                else if (currentMode === 'starred') matchMode = starSet.has(url);
                else if (currentMode === 'raw-all') matchMode = true;

                let matchPlat = (currentPlatform === 'all') || (plat === currentPlatform);
                let matchSearch = (!q) || text.includes(q);

                if (matchMode && matchPlat && matchSearch) {
                    card.style.display = 'flex';
                    visible++;
                } else {
                    card.style.display = 'none';
                }
            });
            document.getElementById('visibleCounter').textContent = visible;
        }

        window.addEventListener('DOMContentLoaded', () => {
            syncCardStates();
            applyAllFilters();
        });
    </script>
</body>
</html>"""

    final_html = (
        html_template
        .replace("__STRICT_COUNT__", str(strict_count))
        .replace("__NOISE_COUNT__", str(noise_count))
        .replace("__SNAP_MAP_URL__", snap_map_url)
        .replace("__TOTAL_COUNT__", str(len(results_db)))
        .replace("__TIER1_COUNT__", str(tier1_strict_count))
        .replace("__TIER2_COUNT__", str(tier2_strict_count))
        .replace("__PLATFORM_BUTTONS__", plat_buttons_html)
        .replace("__CARDS_HTML__", cards_html)
    )

    with open("results.html", "w", encoding="utf-8") as f:
        f.write(final_html)
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(list(results_db.values()), f, ensure_ascii=False, indent=2)
    print(f"[+] اكتمل التحديث V6! الصافي المرتبط بالبقيع: {strict_count} | المعزول تلقائياً: {noise_count}")

if __name__ == "__main__":
    load_previous_results()
    search_ultra_specific_burial_scenes()
    generate_html_report()
