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

CORE_BAQI_TERMS = [
    "مقبرة البقيع", "بقيع الغرقد", "دفن في البقيع", "جنازة البقيع",
    "jannatul baqi", "pemakaman baqi", "جنت البقیع", "cennetül baki",
    "кладбище баки", "baqi qabristoni", "জান্নাতুল বাকি"
]

ALL_PLATFORMS_ORDER = [
    "YouTube", "TikTok", "Snapchat", "Instagram", "Facebook",
    "VK", "Telegram", "X", "Dailymotion", "Likee_Kwai", "Other"
]

results_db = {}

def load_previous_results():
    """تحميل جميع النتائج السابقة من الذاكرة التراكمية"""
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
    if "likee.video" in u or "kwai.com" in u or "threads.net" in u or "threads.com" in u:
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
    if any(x in d_str for x in ["2025-08-05", "5 Aug 2025", "Aug 5, 2025", "5 أغسطس", "05.08.2025"]):
        return 1
    if any(x in d_str for x in [
        "2025-08-04", "2025-08-06", "2025-08-07", "2025-08-08",
        "Aug 4, 2025", "Aug 6, 2025", "Aug 7, 2025", "Aug 8, 2025",
        "4 أغسطس", "6 أغسطس", "7 أغسطس", "8 أغسطس"
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
    """إرسال طلب قياسي نظيف بدون معامل num لضمان قبول 100% من طلبات الويب والفيديو"""
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
            api_status["serper"] = "✅ متصل ويعمل (ويب + فيديو)"
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
        else:
            print(f"[!] تنبيه Serper ({endpoint} - {res.status_code}): { res.text[:100] }")
    except Exception as e:
        print(f"[!] استثناء في اتصال Serper: {e}")
    return count_added

def search_tiktok_direct_api():
    """مسح قاعدة بيانات تيك توك مباشرة لجلب الفيديوهات مع صورها المصغرة وتاريخ الرفع بالثانية"""
    print("[*] 1/3 جاري المسح المباشر لقاعدة بيانات TikTok الداخلية...")
    direct_keywords = [
        "دفن في البقيع", "مقبرة البقيع", "جنازة البقيع", "بقيع الغرقد", "البقيع",
        "pemakaman baqi", "jannatul baqi", "makam baqi", "جنت البقیع",
        "cennetül baki", "кладбище баки", "baqi qabristoni", "জান্নাতুল বাকি"
    ]
    for kw in direct_keywords:
        for cursor in [0, 30]:
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
                        # الاحتفاظ بالفيديوهات المرفوعة في أغسطس وسبتمبر 2025
                        if 1754000000 <= c_time <= 1759276800:
                            vid_id = v.get("video_id", "")
                            author = v.get("author", {}).get("unique_id", "user")
                            url = f"https://www.tiktok.com/@{author}/video/{vid_id}"
                            title = v.get("title") or f"فيديو تيك توك (@{author})"
                            thumb = v.get("cover", "")
                            dt_str = datetime.fromtimestamp(c_time, tz=AST_TZ).strftime("%Y-%m-%d %H:%M:%S (توقيت المدينة)")
                            tier = classify_tier(dt_str, c_time)
                            add_result(
                                url, title, "TikTok", f"رادار تيك توك المباشر ({kw})",
                                f"وقت الرفع الدقيق: {dt_str}", thumb, title, tier
                            )
            except Exception as e:
                print(f"[!] تنبيه TikTok المباشر: {e}")
            time.sleep(0.9)

def search_missing_platforms_clean():
    """المسح المزدوج (Search + Videos) بدون معامل num للمنصات الخمس: Snapchat, VK, Telegram, X, Likee/Kwai"""
    if not SERPER_API_KEY:
        api_status["serper"] = "❌ المفتاح غير موجود"
        return

    print("[*] 2/3 جاري المسح المزدوج لـ Snapchat و VK و Telegram و X و Likee/Kwai...")

    platform_targets = [
        ("Snapchat", "site:snapchat.com", [
            "البقيع", "مقبرة البقيع", "بقيع الغرقد", "المدينة المنورة البقيع",
            "jannatul baqi", "madinah baqi", "جنت البقیع", "pemakaman baqi"
        ]),
        ("VK", "site:vk.com", [
            "кладбище баки", "джаннат аль баки", "медина баки", "аль баки",
            "baqi qabristoni", "jannatul baqi", "البقيع", "بقيع"
        ]),
        ("VK", "site:ok.ru", [
            "кладбище баки", "джаннат аль баки", "медина баки", "baqi"
        ]),
        ("Telegram", "site:t.me", [
            "مقبرة البقيع", "دفن في البقيع", "جنازة البقيع", "بقيع الغرقد",
            "البقيع أغسطس 2025", "البقيع صفر 1447", "jannatul baqi",
            "pemakaman baqi", "جنت البقیع", "кладбище баки", "baqi qabristoni"
        ]),
        ("X", "site:x.com", [
            "مقبرة البقيع", "دفن البقيع", "جنازة البقيع", "بقيع الغرقد",
            "jannatul baqi", "pemakaman baqi", "جنت البقیع", "cennetül baki"
        ]),
        ("X", "site:twitter.com", [
            "مقبرة البقيع", "دفن البقيع", "جنازة البقيع", "jannatul baqi"
        ]),
        ("Likee_Kwai", "site:kwai.com", [
            "البقيع", "مقبرة البقيع", "جنازة البقيع", "jannatul baqi", "pemakaman baqi"
        ]),
        ("Likee_Kwai", "site:likee.video", [
            "البقيع", "jannatul baqi", "جنت البقیع", "pemakaman baqi"
        ]),
        ("Likee_Kwai", "site:threads.net", [
            "مقبرة البقيع", "البقيع", "jannatul baqi", "pemakaman baqi"
        ])
    ]

    for plat_name, site_op, terms in platform_targets:
        for term in terms:
            q = f"{site_op} {term}"
            # 1. فحص عبر محرك الويب القياسي (بدون num)
            serper_request(q, f"{plat_name} ({term})", endpoint="search", forced_platform=plat_name)
            time.sleep(0.12)
            # 2. فحص عبر محرك الفيديوهات لجلب المقاطع المصورة مباشرة
            serper_request(q, f"{plat_name} فيديو ({term})", endpoint="videos", forced_platform=plat_name)
            time.sleep(0.12)

    api_status["snapmap"] = "✅ تم مسح Snapchat والمنصات"

def search_deep_date_queries():
    """3/3 مسح إضافي دقيق بالتواريخ الهجرية والميلادية لأيام 5 و 6 و 7 أغسطس (11 و 12 و 13 صفر)"""
    if not SERPER_API_KEY:
        return
    print("[*] 3/3 جاري المسح الدقيق بالتواريخ الهجرية والميلادية...")
    exact_date_queries = [
        "البقيع 5 أغسطس 2025", "البقيع 6 أغسطس 2025", "البقيع 11 صفر 1447", "البقيع 12 صفر 1447",
        "baqi 5 agustus 2025", "baqi 6 agustus 2025", "jannatul baqi august 5 2025",
        "jannatul baqi 5 august 2025", "baki 5 ağustos 2025", "جنت البقیع 5 اگست 2025"
    ]
    for eq in exact_date_queries:
        serper_request(eq, "تطابق تاريخي دقيق", endpoint="videos")
        time.sleep(0.12)
        serper_request(eq, "تطابق تاريخي دقيق", endpoint="search")
        time.sleep(0.12)

def generate_html_report():
    """بناء لوحة النتائج المحدثة"""
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

    plat_buttons_html = ""
    for plat in ALL_PLATFORMS_ORDER:
        count = platform_counts.get(plat, 0)
        btn_style = 'style="border:1px solid #38bdf8;"' if count > 0 else 'style="opacity:0.65;"'
        plat_buttons_html += f'<button class="filter-btn" {btn_style} onclick="filterByPlatform(\'{plat}\', this)">{plat} ({count})</button>\n'

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

    snap_map_url = f"https://map.snapchat.com/@{LAT},{LON},18.00z"

    html_template = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>رادار تنقيب البقيع الشامل - 5 أغسطس 2025</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .header { max-width: 1280px; margin: 0 auto 20px; background: #1e293b; padding: 20px; border-radius: 14px; border: 1px solid #334155; }
        .stats-bar { display: flex; gap: 15px; flex-wrap: wrap; margin: 10px 0; padding: 12px; background: #0f172a; border-radius: 10px; font-size: 14px; }
        .api-bar { display: flex; gap: 15px; flex-wrap: wrap; margin: 8px 0; padding: 10px 14px; background: #172554; border: 1px solid #1d4ed8; border-radius: 10px; font-size: 13px; align-items: center; }
        .snap-btn { background: #eab308; color: #000; text-decoration: none; padding: 7px 14px; border-radius: 8px; font-weight: bold; font-size: 13px; margin-right: auto; }
        .snap-btn:hover { background: #facc15; }
        .search-box { width: 100%; padding: 12px 15px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; font-size: 15px; margin-top: 10px; box-sizing: border-box; }
        .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
        .filter-btn { background: #334155; color: #fff; border: none; padding: 8px 13px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 13px; transition: 0.15s; }
        .filter-btn.active, .filter-btn:hover { background: #2563eb; opacity: 1 !important; }
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
        <div class="api-bar">
            <span>📡 YouTube: <strong>__YT_STATUS__</strong></span>
            <span>🌐 Serper Multi-Platform: <strong>__SERPER_STATUS__</strong></span>
            <span>👻 رادار المنصات الإضافية: <strong>__SNAP_STATUS__</strong></span>
            <a href="__SNAP_MAP_URL__" target="_blank" rel="noopener" class="snap-btn">🗺️ فتح خريطة السناب فوق إحداثيات القبر مباشرة ↗</a>
        </div>
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
    print(f"[+] اكتمل التحديث بنجاح! الإجمالي الآن: {len(results_db)} نتيجة (منها {new_count} جديدة).")

if __name__ == "__main__":
    load_previous_results()
    search_tiktok_direct_api()
    search_missing_platforms_clean()
    search_deep_date_queries()
    generate_html_report()
