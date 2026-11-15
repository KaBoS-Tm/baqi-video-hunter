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
    "youtube": "محفوظ بالذاكرة + متصل",
    "serper": "غير مفعل",
    "snapmap": "جاهز"
}

ALL_PLATFORMS_ORDER = [
    "YouTube", "TikTok", "Snapchat", "Instagram", "Facebook",
    "VK", "Telegram", "X", "Dailymotion", "Likee_Kwai", "Other"
]

results_db = {}

def load_previous_results():
    """تحميل جميع النتائج السابقة من الذاكرة التراكمية (2261+ فيديو)"""
    if os.path.exists("results.json"):
        try:
            with open("results.json", "r", encoding="utf-8") as f:
                old_list = json.load(f)
                for item in old_list:
                    item["is_new"] = False
                    results_db[item["url"]] = item
            print(f"[*] تم تحميل {len(results_db)} نتيجة سابقة من الذاكرة.")
        except Exception as e:
            print(f"[!] تنبيه عند قراءة الذاكرة السابقة: {e}")

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
        return

    results_db[clean_url] = {
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
            api_status["serper"] = "✅ متصل ويعمل بأعلى كفاءة"
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

def search_tiktok_deep_pages():
    """1. التعمق في الصفحات الخلفية لقاعدة بيانات تيك توك (Cursors 60, 90, 120)"""
    print("[*] 1/4 جاري التعمق في الصفحات الخلفية لـ TikTok...")
    deep_keywords = [
        "دفن في البقيع", "مقبرة البقيع", "جنازة البقيع", "بقيع الغرقد", "فجر البقيع",
        "pemakaman baqi", "jannatul baqi", "makam baqi", "kuburan baqi", "جنت البقیع",
        "بقیع قبرستان", "cennetül baki", "baki mezarlığı", "кладбище баки", "baqi qabristoni"
    ]
    for kw in deep_keywords:
        for cursor in [60, 90, 120]:
            try:
                res = requests.post(
                    "https://www.tikwm.com/api/feed/search",
                    data={"keywords": kw, "count": 30, "cursor": cursor},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=12
                )
                if res.status_code == 200:
                    data = res.json().get("data", {})
                    videos = data.get("videos", []) if isinstance(data, dict) else []
                    for v in videos:
                        c_time = int(v.get("create_time", 0))
                        if 1754000000 <= c_time <= 1759276800:
                            vid_id = v.get("video_id", "")
                            author = v.get("author", {}).get("unique_id", "user")
                            url = f"https://www.tiktok.com/@{author}/video/{vid_id}"
                            title = v.get("title") or f"فيديو تيك توك (@{author})"
                            thumb = v.get("cover", "")
                            dt_str = datetime.fromtimestamp(c_time, tz=AST_TZ).strftime("%Y-%m-%d %H:%M:%S (توقيت المدينة)")
                            tier = classify_tier(dt_str, c_time)
                            add_result(
                                url, title, "TikTok", f"تعمق تيك توك ({kw})",
                                f"وقت الرفع الدقيق: {dt_str}", thumb, title, tier
                            )
            except Exception as e:
                print(f"[!] تنبيه TikTok: {e}")
            time.sleep(0.8)

def search_numeric_dates_all_platforms():
    """2. البحث بصيغ التواريخ الرقمية الدقيقة والوسوم (Hashtags) عبر جميع المنصات"""
    if not SERPER_API_KEY:
        return
    print("[*] 2/4 جاري المسح بصيغ التواريخ الرقمية والهجري...")
    numeric_queries = [
        'البقيع "5/8/2025"', 'البقيع "05/08/2025"', 'البقيع "2025/08/05"', 'البقيع "2025-08-05"',
        'البقيع "6/8/2025"', 'البقيع "11/2/1447"', 'البقيع "11/02/1447"', 'البقيع "12/2/1447"',
        'البقيع "11 صفر"', 'البقيع "12 صفر"', 'دفن البقيع صفر 1447', 'جنازة البقيع أغسطس 2025',
        'baqi "05/08/2025"', 'baqi "5/8/2025"', 'baqi "2025-08-05"', 'baqi "5 agustus"',
        'baqi "6 agustus"', 'jannatul baqi "august 5"', 'jannatul baqi "5 august"',
        'baki "5 ağustos"', 'baki "05.08.2025"', 'баки "05.08.2025"', 'جنت البقیع "5 اگست"'
    ]
    for nq in numeric_queries:
        serper_request(nq, "تاريخ رقمي دقيق", endpoint="videos")
        time.sleep(0.12)
        serper_request(nq, "تاريخ رقمي دقيق", endpoint="search")
        time.sleep(0.12)

def search_targeted_time_window_social():
    """3. مسح المنصات بنافذة زمنية ضيقة جداً (4 إلى 12 أغسطس 2025)"""
    if not SERPER_API_KEY:
        return
    print("[*] 3/4 جاري مسح المنصات في النافذة الزمنية الضيقة (4-12 أغسطس)...")
    sites = [
        ("TikTok", "site:tiktok.com"),
        ("Instagram", "site:instagram.com"),
        ("Facebook", "site:facebook.com"),
        ("Snapchat", "site:snapchat.com"),
        ("X", "site:x.com"),
        ("Telegram", "site:t.me"),
        ("VK", "site:vk.com")
    ]
    core_words = [
        "البقيع", "بقيع الغرقد", "جنازة", "دفن", "jannatul baqi",
        "pemakaman baqi", "makam baqi", "جنت البقیع", "cennetül baki", "кладбище баки"
    ]
    for plat_name, site_op in sites:
        for w in core_words:
            q = f"{site_op} {w} after:2025-08-04 before:2025-08-12"
            serper_request(q, f"نافذة 4-12 أغسطس ({w})", endpoint="search", forced_platform=plat_name)
            time.sleep(0.12)

def search_asian_regional_platforms():
    """4. مسح المنصات الإقليمية الآسيوية والمنتديات (SnackVideo, ShareChat, Moj, Bilibili, Reddit, Pinterest)"""
    if not SERPER_API_KEY:
        return
    print("[*] 4/4 جاري مسح منصات جنوب وشرق آسيا الإضافية (SnackVideo, ShareChat, Moj, Bilibili, Reddit)...")
    extra_targets = [
        ("Likee_Kwai", "site:snackvideo.com", ["baqi", "makam baqi", "pemakaman baqi", "madinah baqi", "جنت البقیع"]),
        ("Likee_Kwai", "site:sharechat.com", ["jannatul baqi", "madina baqi", "جنت البقیع"]),
        ("Likee_Kwai", "site:mojapp.in", ["jannatul baqi", "baqi madina"]),
        ("Other", "site:bilibili.com", ["jannatul baqi", "madinah baqi", "麦地那"]),
        ("Other", "site:reddit.com", ["jannatul baqi", "al baqi burial", "baqi cemetery"]),
        ("Other", "site:pinterest.com", ["jannatul baqi 2025", "pemakaman baqi", "مقبرة البقيع"])
    ]
    for plat_name, site_op, terms in extra_targets:
        for t in terms:
            serper_request(f"{site_op} {t}", f"منصة إقليمية ({t})", endpoint="search", forced_platform=plat_name)
            time.sleep(0.12)

    api_status["snapmap"] = "✅ اكتمل المسح الشامل لـ 15+ منصة"

def generate_html_report():
    """بناء لوحة التحكم الذكية V5 مع الفلترة المتقاطعة وحفظ المشاهدات والمفضلة"""
    sorted_items = sorted(
        results_db.values(),
        key=lambda x: (x.get("tier", 3), not x.get("is_new", False), x.get("published_at", ""))
    )

    platform_counts = {p: 0 for p in ALL_PLATFORMS_ORDER}
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

    plat_buttons_html = f'<button class="filter-btn plat-btn active" onclick="setPlatformFilter(\'all\', this)">كل المنصات ({len(results_db)})</button>\n'
    for plat in ALL_PLATFORMS_ORDER:
        count = platform_counts.get(plat, 0)
        btn_style = 'style="border:1px solid #38bdf8;"' if count > 0 else 'style="opacity:0.6;"'
        plat_buttons_html += f'<button class="filter-btn plat-btn" {btn_style} onclick="setPlatformFilter(\'{plat}\', this)">{plat} ({count})</button>\n'

    cards_html = ""
    for item in sorted_items:
        tier = item.get("tier", 3)
        is_new = item.get("is_new", False)
        url_safe = item["url"].replace('"', '&quot;')
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
        <div class="{card_class}" data-url="{url_safe}" data-tier="{tier}" data-platform="{item['platform']}" data-new="{str(is_new).lower()}" data-search="{search_text}">
            {thumb_html}
            <div class="card-body">
                <div class="tags">
                    {new_badge}
                    <span class="badge plat">{item['platform']}</span>
                    <span class="badge lang">{item['lang']}</span>
                    {tier_badge}
                    <span class="seen-label" style="display:none;">✔️ تمت المشاهدة</span>
                </div>
                <h3><a href="{url_safe}" target="_blank" rel="noopener" onclick="markAsSeen('{url_safe}')">{item['title']}</a></h3>
                <p class="date">{item['published_at']}</p>
                <p class="snippet">{item['snippet'][:180]}</p>
                <div class="card-actions">
                    <a class="open-btn" href="{url_safe}" target="_blank" rel="noopener" onclick="markAsSeen('{url_safe}')">مشاهدة الفيديو ↗</a>
                    <button class="star-btn" onclick="toggleStar('{url_safe}', this)" title="إضافة للمفضلة / المشتبه به">⭐</button>
                    <button class="seen-btn" onclick="toggleSeenManual('{url_safe}', this)" title="تحديد كمشاهد / غير مشاهد">👁️</button>
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
    <title>رادار تنقيب البقيع الشامل V5 - 5 أغسطس 2025</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .header { max-width: 1280px; margin: 0 auto 20px; background: #1e293b; padding: 20px; border-radius: 14px; border: 1px solid #334155; }
        .stats-bar { display: flex; gap: 15px; flex-wrap: wrap; margin: 10px 0; padding: 12px; background: #0f172a; border-radius: 10px; font-size: 14px; align-items: center; }
        .api-bar { display: flex; gap: 15px; flex-wrap: wrap; margin: 8px 0; padding: 10px 14px; background: #172554; border: 1px solid #1d4ed8; border-radius: 10px; font-size: 13px; align-items: center; }
        .snap-btn { background: #eab308; color: #000; text-decoration: none; padding: 7px 14px; border-radius: 8px; font-weight: bold; font-size: 13px; margin-right: auto; }
        .search-box { width: 100%; padding: 12px 15px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; font-size: 15px; margin-top: 10px; box-sizing: border-box; }
        .filter-group-title { font-size: 12px; color: #94a3b8; margin-top: 12px; margin-bottom: 4px; font-weight: bold; }
        .filters { display: flex; gap: 8px; flex-wrap: wrap; }
        .filter-btn { background: #334155; color: #fff; border: none; padding: 8px 13px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 13px; transition: 0.15s; }
        .filter-btn.active, .filter-btn:hover { background: #2563eb; opacity: 1 !important; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 18px; max-width: 1280px; margin: 0 auto; }
        .card { background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; display: flex; flex-direction: column; transition: 0.2s; }
        .card.seen-card { opacity: 0.45; border-color: #475569 !important; box-shadow: none !important; }
        .card.starred-card { border: 2px solid #f59e0b !important; box-shadow: 0 0 18px rgba(245, 158, 11, 0.4) !important; opacity: 1 !important; }
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
        .seen-label { background: #64748b; color: #fff; font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: bold; }
        .tier-badge { font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: bold; }
        .t1 { background: #16a34a; color: #fff; }
        .t2 { background: #ca8a04; color: #fff; }
        .t3 { background: #334155; color: #cbd5e1; }
        h3 { margin: 0 0 8px; font-size: 15px; line-height: 1.4; }
        h3 a { color: #38bdf8; text-decoration: none; }
        .date { font-size: 13px; color: #fde047; margin: 0 0 8px; font-weight: bold; }
        .snippet { font-size: 13px; color: #cbd5e1; margin: 0 0 15px; flex: 1; word-break: break-word; }
        .card-actions { display: flex; gap: 8px; align-items: center; }
        .open-btn { flex: 1; text-align: center; background: #2563eb; color: white; text-decoration: none; padding: 9px; border-radius: 6px; font-size: 14px; font-weight: bold; }
        .open-btn:hover { background: #1d4ed8; }
        .star-btn, .seen-btn { background: #334155; border: 1px solid #475569; color: #fff; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .star-btn.active { background: #f59e0b; color: #000; border-color: #f59e0b; }
    </style>
</head>
<body>
    <div class="header">
        <h2>رادار تنقيب البقيع الشامل (الثلاثاء 5 أغسطس 2025 / 11 صفر 1447 هـ)</h2>
        <div class="api-bar">
            <span>📡 YouTube: <strong>__YT_STATUS__</strong></span>
            <span>🌐 Serper Multi-Platform: <strong>__SERPER_STATUS__</strong></span>
            <span>👻 المنصات الإضافية: <strong>__SNAP_STATUS__</strong></span>
            <a href="__SNAP_MAP_URL__" target="_blank" rel="noopener" class="snap-btn">🗺️ فتح خريطة السناب فوق إحداثيات القبر مباشرة ↗</a>
        </div>
        <div class="stats-bar">
            <span>📦 الإجمالي التراكمي: <strong>__TOTAL_COUNT__</strong></span>
            <span>🆕 مكتشف في هذه الجولة: <strong>__NEW_COUNT__</strong></span>
            <span>🟢 يوم الدفن (5 أغسطس): <strong>__TIER1_COUNT__</strong></span>
            <span>🟡 أيام المربع (4 و 6-8 أغسطس): <strong>__TIER2_COUNT__</strong></span>
            <span>👁️ شاهدته أنت: <strong id="seenCounter">0</strong></span>
            <span>⭐ المفضلة: <strong id="starCounter">0</strong></span>
            <span>🔍 المعروض الآن: <strong id="visibleCounter">__TOTAL_COUNT__</strong></span>
        </div>
        <input type="text" id="searchInput" class="search-box" placeholder="🔍 ابحث فوراً داخل النتائج (مثال: فجر، جنازة، باقي، 5 أغسطس، اسم لغة أو كلمة)..." oninput="applyAllFilters()">
        
        <div class="filter-group-title">1️⃣ فلتر الأولوية الزمنية وحالة المشاهدة (يمكن دمجه مع أي منصة بالأسفل):</div>
        <div class="filters">
            <button class="filter-btn mode-btn active" onclick="setModeFilter('all', this)">عرض الكل (__TOTAL_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #ec4899" onclick="setModeFilter('new', this)">🆕 الجديد فقط (__NEW_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #22c55e" onclick="setModeFilter('tier-1', this)">🟢 يوم الدفن: 5 أغسطس (__TIER1_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #eab308" onclick="setModeFilter('tier-2', this)">🟡 نفس المربع: 4 و 6-8 أغسطس (__TIER2_COUNT__)</button>
            <button class="filter-btn mode-btn" style="border:1px solid #f59e0b" onclick="setModeFilter('starred', this)">⭐ المفضلة والمشتبه به</button>
            <button class="filter-btn mode-btn" style="border:1px solid #38bdf8" onclick="setModeFilter('unseen', this)">🙈 لم أشاهده بعد فقط</button>
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
        let currentMode = 'all';
        let currentPlatform = 'all';
        let seenSet = new Set(JSON.parse(localStorage.getItem('baqi_seen_urls') || '[]'));
        let starSet = new Set(JSON.parse(localStorage.getItem('baqi_star_urls') || '[]'));

        function saveStorage() {
            localStorage.setItem('baqi_seen_urls', JSON.stringify([...seenSet]));
            localStorage.setItem('baqi_star_urls', JSON.stringify([...starSet]));
            document.getElementById('seenCounter').textContent = seenSet.size;
            document.getElementById('starCounter').textContent = starSet.size;
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
                const tier = card.dataset.tier;
                const plat = card.dataset.platform;
                const isNew = card.dataset.new === 'true';
                const text = (card.dataset.search || '').toLowerCase();

                let matchMode = true;
                if (currentMode === 'new') matchMode = isNew;
                else if (currentMode === 'tier-1') matchMode = (tier === '1');
                else if (currentMode === 'tier-2') matchMode = (tier === '2');
                else if (currentMode === 'starred') matchMode = starSet.has(url);
                else if (currentMode === 'unseen') matchMode = !seenSet.has(url);

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
        .replace("__YT_STATUS__", api_status["youtube"])
        .replace("__SERPER_STATUS__", api_status["serper"])
        .replace("__SNAP_STATUS__", api_status["snapmap"])
        .replace("__SNAP_MAP_URL__", snap_map_url)
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
    print(f"[+] اكتمل التحديث V5 بنجاح! الإجمالي الآن: {len(results_db)} نتيجة (منها {new_count} جديدة).")

if __name__ == "__main__":
    load_previous_results()
    search_tiktok_deep_pages()
    search_numeric_dates_all_platforms()
    search_targeted_time_window_social()
    search_asian_regional_platforms()
    generate_html_report()
