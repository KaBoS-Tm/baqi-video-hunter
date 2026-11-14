import os
import re
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# توقيت المدينة المنورة (UTC+3)
AST_TZ = timezone(timedelta(hours=3))

# إحداثيات القبر الدقيقة داخل البقيع
LAT_LON = "24.466694,39.614944"

# النطاق الزمني الشامل (من فجر 5 أغسطس حتى 25 أغسطس لمن تأخر في الرفع)
START_DATE_ISO = "2025-08-05T01:00:00Z"
END_DATE_ISO = "2025-08-25T23:59:59Z"

# النطاق الزمني الضيق لتتبع نفس المربع (من 4 أغسطس إلى 8 أغسطس)
SQUARE_START_ISO = "2025-08-04T00:00:00Z"
SQUARE_END_ISO = "2025-08-08T23:59:59Z"

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# 1. مصفوفة كلمات الدفن المباشرة بـ 8 لغات
BURIAL_QUERIES = {
    "Arabic": [
        "دفن في البقيع", "مقبرة البقيع دفن", "جنازة البقيع", "بقيع الغرقد دفن",
        "البقيع بعد الفجر", "دفن موتى البقيع", "البقيع 11 صفر", "البقيع 12 صفر",
        "البقيع 5 أغسطس", "البقيع 6 أغسطس"
    ],
    "Indonesian_Malay": [
        "pemakaman baqi", "pemakaman di baqi madinah", "makam baqi", "kuburan baqi",
        "jannatul baqi pemakaman", "penguburan baqi", "jenazah di baqi",
        "baqi 5 agustus 2025", "baqi 6 agustus 2025"
    ],
    "Urdu_Hindi": [
        "جنت البقیع تدفین", "جنت البقیع قبرستان", "بقیع میں تدفین", "جنت البقیع جنازہ",
        "jannatul baqi burial", "jannat ul baqi qabristan", "baqi madinah janaza"
    ],
    "Turkish": [
        "cennetül baki defin", "baki mezarlığı cenaze", "medine baki kabristanı",
        "cennetül baki cenaze", "baki 5 ağustos", "baki 6 ağustos"
    ],
    "Russian_CentralAsia": [
        "кладбище баки похороны", "джаннат аль баки", "похороны в медина баки",
        "baqi qabristoni", "мадина баки дафн"
    ],
    "Bengali": [
        "জান্নাতুল বাকি দাফন", "মদিনা জান্নাতুল বাকি", "জান্নাতুল বাকি কবরস্থান"
    ],
    "Persian": [
        "دفن در بقیع", "قبرستان بقیع تدفین", "جنت البقیع مدینه"
    ],
    "English_French": [
        "jannatul baqi burial", "al baqi cemetery burial", "burying in baqi madinah",
        "enterrement baqi médine", "cimetière al baqi"
    ]
}

# 2. كلمات عامة عن البقيع (تُستخدم فقط داخل نافذة المربع الزمنية الضيقة 4-8 أغسطس)
# لاصطياد من صوّر الدفن وكتب فقط "البقيع" بدون كلمة "دفن"
SQUARE_WINDOW_QUERIES = [
    "مقبرة البقيع", "بقيع الغرقد", "زيارة البقيع", "البقيع اليوم", "البقيع الفجر",
    "jannatul baqi", "baqi madinah", "makam baqi madinah", "cennetül baki", "جنت البقیع"
]

SOCIAL_SITES = [
    "site:tiktok.com",
    "site:instagram.com/reel",
    "site:instagram.com/p",
    "site:facebook.com/reel",
    "site:facebook.com/watch",
    "site:vk.com/video",
    "site:vk.com/clip",
    "site:x.com"
]

results_db = {}

def decode_tiktok_timestamp(url):
    """استخراج وقت الرفع الدقيق بالثانية من رقم فيديو تيك توك"""
    match = re.search(r"/video/(\d{19})", url)
    if match:
        vid_id = int(match.group(1))
        unix_ts = vid_id >> 32
        dt = datetime.fromtimestamp(unix_ts, tz=AST_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S (توقيت المدينة)"), unix_ts, dt
    return None, 0, None

def classify_tier(date_text, unix_ts=0):
    """تصنيف الفيديو: (1: يوم الدفن 5 أغسطس) (2: نفس المربع 4 أو 6-8 أغسطس) (3: رفع متأخر)"""
    if unix_ts > 0:
        # 5 أغسطس من 4 فجراً إلى نهاية اليوم بتوقيت المدينة
        if 1754355600 <= unix_ts <= 1754427599:
            return 1
        # 4 أغسطس أو 6-8 أغسطس (نفس المربع)
        if 1754254800 <= unix_ts <= 1754686799:
            return 2
        return 3

    if "2025-08-05" in date_text or "5 Aug 2025" in date_text or "Aug 5, 2025" in date_text:
        return 1
    for d in ["2025-08-04", "2025-08-06", "2025-08-07", "2025-08-08", "Aug 6, 2025", "Aug 7, 2025"]:
        if d in date_text:
            return 2
    return 3

def add_result(url, title, platform, lang, published_at, thumbnail="", snippet="", tier=3):
    if url in results_db:
        if tier < results_db[url]["tier"]:
            results_db[url]["tier"] = tier
        return
    results_db[url] = {
        "url": url,
        "title": title or "بدون عنوان",
        "platform": platform,
        "lang": lang,
        "published_at": published_at,
        "thumbnail": thumbnail,
        "snippet": snippet,
        "tier": tier
    }

def search_youtube_geo():
    """1. رادار يوتيوب الجغرافي الدقيق حول إحداثيات القبر"""
    if not YOUTUBE_API_KEY:
        print("[!] YOUTUBE_API_KEY غير متوفر.")
        return

    print("[*] جاري مسح يوتيوب بالإحداثيات الجغرافية حول القبر والمربع المحيط...")
    for radius in ["500m", "1500m"]:
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
        res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
        if res.status_code == 200:
            for item in res.json().get("items", []):
                vid_id = item["id"]["videoId"]
                snip = item["snippet"]
                url = f"https://www.youtube.com/watch?v={vid_id}"
                pub = snip.get("publishedAt", "")
                thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                tier = classify_tier(pub)
                add_result(
                    url=url,
                    title=snip.get("title"),
                    platform="YouTube",
                    lang=f"إحداثيات ({radius})",
                    published_at=pub,
                    thumbnail=thumb,
                    snippet=snip.get("description", ""),
                    tier=tier
                )
        time.sleep(0.4)

def search_youtube_keywords():
    """2. مسح يوتيوب بكلمات الدفن + مسح المربع الزمني الضيق (4-8 أغسطس)"""
    if not YOUTUBE_API_KEY:
        return

    print("[*] جاري مسح يوتيوب بمصفوفة اللغات...")
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
                    add_result(
                        url=url,
                        title=snip.get("title"),
                        platform="YouTube",
                        lang=lang,
                        published_at=pub,
                        thumbnail=thumb,
                        snippet=snip.get("description", ""),
                        tier=classify_tier(pub)
                    )
            time.sleep(0.3)

    print("[*] جاري مسح يوتيوب لجميع فيديوهات البقيع العامة خلال أيام المربع (4-8 أغسطس)...")
    for kw in SQUARE_WINDOW_QUERIES:
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
                add_result(
                    url=url,
                    title=snip.get("title"),
                    platform="YouTube",
                    lang="مسح المربع (4-8 أغسطس)",
                    published_at=pub,
                    thumbnail=thumb,
                    snippet=snip.get("description", ""),
                    tier=classify_tier(pub)
                )
        time.sleep(0.3)

def run_serper_query(dork_query, lang_label):
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = json.dumps({"q": dork_query, "num": 30})
    res = requests.post("https://google.serper.dev/search", headers=headers, data=payload)
    if res.status_code != 200:
        return

    for item in res.json().get("organic", []):
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        date_str = item.get("date", "ضمن نطاق البحث")
        unix_ts = 0

        platform = "Other"
        if "tiktok.com" in link:
            platform = "TikTok"
            tt_date, unix_ts, _ = decode_tiktok_timestamp(link)
            if tt_date:
                date_str = f"وقت الرفع الدقيق: {tt_date}"
                # استبعاد أي فيديو تيك توك أقدم من 4 أغسطس 2025
                if unix_ts < 1754254800:
                    continue
        elif "instagram.com" in link:
            platform = "Instagram"
        elif "facebook.com" in link:
            platform = "Facebook"
        elif "vk.com" in link:
            platform = "VK"
        elif "x.com" in link or "twitter.com" in link:
            platform = "X"

        tier = classify_tier(date_str, unix_ts)
        add_result(
            url=link,
            title=title,
            platform=platform,
            lang=lang_label,
            published_at=date_str,
            thumbnail="",
            snippet=snippet,
            tier=tier
        )

def search_social_platforms():
    """3. مسح منصات التواصل (TikTok, Instagram, FB, VK, X)"""
    if not SERPER_API_KEY:
        print("[!] SERPER_API_KEY غير متوفر.")
        return

    sites_filter = " OR ".join(SOCIAL_SITES)

    print("[*] جاري مسح منصات التواصل بكلمات الدفن بجميع اللغات...")
    for lang, keywords in BURIAL_QUERIES.items():
        for kw in keywords:
            dork = f'({sites_filter}) "{kw}" after:2025-08-04 before:2025-08-25'
            run_serper_query(dork, lang)
            time.sleep(0.3)

    print("[*] جاري مسح منصات التواصل لكل ما نُشر عن البقيع في أيام المربع (4-8 أغسطس)...")
    for kw in SQUARE_WINDOW_QUERIES:
        dork = f'({sites_filter}) "{kw}" after:2025-08-04 before:2025-08-09'
        run_serper_query(dork, "مسح المربع (4-8 أغسطس)")
        time.sleep(0.3)

def generate_html_report():
    """توليد صفحة نتائج تفاعلية مع أزرار فلترة حسب اليوم والمنصة"""
    sorted_items = sorted(results_db.values(), key=lambda x: (x["tier"], x["published_at"]))

    cards_html = ""
    for item in sorted_items:
        tier = item["tier"]
        if tier == 1:
            tier_badge = '<span class="tier-badge t1">يوم الدفن (5 أغسطس / 11 صفر)</span>'
            card_class = "card tier-1"
        elif tier == 2:
            tier_badge = '<span class="tier-badge t2">نفس المربع (4 أو 6-8 أغسطس)</span>'
            card_class = "card tier-2"
        else:
            tier_badge = '<span class="tier-badge t3">نافذة الرفع المتأخر</span>'
            card_class = "card tier-3"

        thumb_html = (
            f'<img src="{item["thumbnail"]}" loading="lazy" alt="thumb">'
            if item["thumbnail"]
            else f'<div class="no-thumb">{item["platform"]} - اضغط لفتح الفيديو</div>'
        )

        cards_html += f"""
        <div class="{card_class}" data-tier="{tier}" data-platform="{item['platform']}">
            {thumb_html}
            <div class="card-body">
                <div class="tags">
                    <span class="badge plat">{item['platform']}</span>
                    <span class="badge lang">{item['lang']}</span>
                    {tier_badge}
                </div>
                <h3><a href="{item['url']}" target="_blank" rel="noopener">{item['title']}</a></h3>
                <p class="date">{item['published_at']}</p>
                <p class="snippet">{item['snippet'][:180]}...</p>
                <a class="open-btn" href="{item['url']}" target="_blank" rel="noopener">مشاهدة الفيديو ↗</a>
            </div>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>تقرير تنقيب فيديو البقيع - 5 أغسطس 2025</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
        .header {{ max-width: 1200px; margin: 0 auto 20px; background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }}
        .filters {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }}
        .filter-btn {{ background: #334155; color: #fff; border: none; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 13px; }}
        .filter-btn.active, .filter-btn:hover {{ background: #2563eb; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto; }}
        .card {{ background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; display: flex; flex-direction: column; }}
        .tier-1 {{ border: 2px solid #22c55e; box-shadow: 0 0 15px rgba(34, 197, 94, 0.25); }}
        .tier-2 {{ border: 2px solid #eab308; }}
        .card img {{ width: 100%; height: 180px; object-fit: cover; }}
        .no-thumb {{ width: 100%; height: 110px; background: #090d16; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-weight: bold; font-size: 14px; }}
        .card-body {{ padding: 15px; flex: 1; display: flex; flex-direction: column; }}
        .tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
        .badge {{ font-size: 11px; padding: 3px 8px; border-radius: 6px; color: white; }}
        .plat {{ background: #475569; }}
        .lang {{ background: #0284c7; }}
        .tier-badge {{ font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: bold; }}
        .t1 {{ background: #16a34a; color: #fff; }}
        .t2 {{ background: #ca8a04; color: #fff; }}
        .t3 {{ background: #334155; color: #cbd5e1; }}
        h3 {{ margin: 0 0 8px; font-size: 15px; line-height: 1.4; }}
        h3 a {{ color: #38bdf8; text-decoration: none; }}
        .date {{ font-size: 13px; color: #fde047; margin: 0 0 8px; font-weight: bold; }}
        .snippet {{ font-size: 13px; color: #cbd5e1; margin: 0 0 15px; flex: 1; }}
        .open-btn {{ text-align: center; background: #2563eb; color: white; text-decoration: none; padding: 9px; border-radius: 6px; font-size: 14px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>نتائج التنقيب عن فيديو الدفن في البقيع (الثلاثاء 5 أغسطس 2025 / 11 صفر 1447 هـ)</h2>
        <p>الإحداثيات: <code>24.466694, 39.614944</code> | إجمالي النتائج المكتشفة: <strong>{len(results_db)}</strong></p>
        <div class="filters">
            <button class="filter-btn active" onclick="filterCards('all')">عرض الكل ({len(results_db)})</button>
            <button class="filter-btn" style="border:1px solid #22c55e" onclick="filterCards('tier-1')">🟢 يوم الدفن: 5 أغسطس</button>
            <button class="filter-btn" style="border:1px solid #eab308" onclick="filterCards('tier-2')">🟡 نفس المربع: 4 و 6-8 أغسطس</button>
            <button class="filter-btn" onclick="filterCards('TikTok')">TikTok فقط</button>
            <button class="filter-btn" onclick="filterCards('YouTube')">YouTube فقط</button>
            <button class="filter-btn" onclick="filterCards('Instagram')">Instagram فقط</button>
            <button class="filter-btn" onclick="filterCards('Facebook')">Facebook فقط</button>
        </div>
    </div>
    <div class="grid" id="cardsGrid">
        {cards_html}
    </div>
    <script>
        function filterCards(criteria) {{
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.card').forEach(card => {{
                if (criteria === 'all') {{
                    card.style.display = 'flex';
                }} else if (criteria === 'tier-1') {{
                    card.style.display = card.dataset.tier === '1' ? 'flex' : 'none';
                }} else if (criteria === 'tier-2') {{
                    card.style.display = card.dataset.tier === '2' ? 'flex' : 'none';
                }} else {{
                    card.style.display = card.dataset.platform === criteria ? 'flex' : 'none';
                }}
            }});
        }}
    </script>
</body>
</html>"""

    with open("results.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(list(results_db.values()), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    search_youtube_geo()
    search_youtube_keywords()
    search_social_platforms()
    generate_html_report()
