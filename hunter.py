import os
import re
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# إعدادات التوقيت (توقيت المدينة المنورة UTC+3)
AST_TZ = timezone(timedelta(hours=3))

# الإحداثيات والنطاق الزمني للحدث
LAT_LON = "24.466694,39.614944"
START_DATE_ISO = "2025-08-05T01:00:00Z"  # 4:00 AM بتوقيت المدينة
END_DATE_ISO = "2025-08-25T23:59:59Z"    # نافذة 20 يوماً لمن تأخر في الرفع

# مفاتيح الواجهات البرمجية (تُسحب من GitHub Secrets)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# مصفوفة الكلمات المفتاحية بأكثر اللغات توثيقاً في البقيع
QUERIES_MATRIX = {
    "Arabic": [
        "دفن في البقيع", "مقبرة البقيع دفن", "جنازة البقيع", "بقيع الغرقد دفن",
        "البقيع بعد الفجر", "دفن موتى البقيع", "البقيع 11 صفر 1447", "البقيع 5 أغسطس 2025"
    ],
    "Indonesian_Malay": [
        "pemakaman baqi", "pemakaman di baqi madinah", "makam baqi", "kuburan baqi",
        "jannatul baqi pemakaman", "penguburan baqi", "jenazah di baqi", "baqi 5 agustus 2025"
    ],
    "Urdu_Hindi": [
        "جنت البقیع تدفین", "جنت البقیع قبرستان", "بقیع میں تدفین", "جنت البقیع مدینہ",
        "jannatul baqi burial", "jannat ul baqi qabristan", "baqi madinah janaza"
    ],
    "Turkish": [
        "cennetül baki defin", "baki mezarlığı cenaze", "medine baki kabristanı",
        "cennetül baki cenaze", "baki mezarlığı 5 ağustos 2025"
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
        return dt.strftime("%Y-%m-%d %H:%M:%S (توقيت المدينة)"), unix_ts
    return None, 0

def add_result(url, title, platform, lang, published_at, thumbnail="", snippet="", priority=False):
    if url in results_db:
        return
    results_db[url] = {
        "url": url,
        "title": title or "بدون عنوان",
        "platform": platform,
        "lang": lang,
        "published_at": published_at,
        "thumbnail": thumbnail,
        "snippet": snippet,
        "priority": priority
    }

def search_youtube_geo():
    """1. البحث بالرادار الجغرافي الدقيق حول إحداثيات القبر في يوتيوب"""
    if not YOUTUBE_API_KEY:
        print("[!] YOUTUBE_API_KEY غير متوفر.")
        return

    print("[*] جاري مسح يوتيوب بالإحداثيات الجغرافية حول البقيع...")
    for radius in ["500m", "1500m"]:
        params = {
            "part": "snippet",
            "type": "video",
            "location": LAT_LON,
            "locationRadius": radius,
            "publishedAfter": START_DATE_ISO,
            "publishedBefore": END_DATE_ISO,
            "maxResults": 50,
            "order": "date",
            "key": YOUTUBE_API_KEY
        }
        res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                vid_id = item["id"]["videoId"]
                snip = item["snippet"]
                url = f"https://www.youtube.com/watch?v={vid_id}"
                pub = snip.get("publishedAt", "")
                thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                is_priority = pub.startswith("2025-08-05") or pub.startswith("2025-08-06")
                add_result(
                    url=url,
                    title=snip.get("title"),
                    platform=f"YouTube Geo ({radius})",
                    lang="إحداثيات مباشرة",
                    published_at=pub,
                    thumbnail=thumb,
                    snippet=snip.get("description", ""),
                    priority=is_priority
                )
        time.sleep(0.5)

def search_youtube_keywords():
    """2. البحث في يوتيوب وشورتس بمصفوفة اللغات ضمن النطاق الزمني"""
    if not YOUTUBE_API_KEY:
        return

    print("[*] جاري مسح يوتيوب بمصفوفة اللغات...")
    for lang, keywords in QUERIES_MATRIX.items():
        for kw in keywords:
            params = {
                "part": "snippet",
                "type": "video",
                "q": kw,
                "publishedAfter": START_DATE_ISO,
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
                    is_priority = pub.startswith("2025-08-05") or pub.startswith("2025-08-06")
                    add_result(
                        url=url,
                        title=snip.get("title"),
                        platform="YouTube / Shorts",
                        lang=lang,
                        published_at=pub,
                        thumbnail=thumb,
                        snippet=snip.get("description", ""),
                        priority=is_priority
                    )
            time.sleep(0.3)

def search_social_platforms():
    """3. مسح TikTok, Instagram, Facebook, VK, X عبر Serper API"""
    if not SERPER_API_KEY:
        print("[!] SERPER_API_KEY غير متوفر.")
        return

    print("[*] جاري مسح منصات التواصل (TikTok, Instagram, FB, VK, X)...")
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }

    sites_filter = " OR ".join(SOCIAL_SITES)

    for lang, keywords in QUERIES_MATRIX.items():
        for kw in keywords:
            # حصر البحث بين 4 أغسطس و 25 أغسطس 2025
            dork_query = f'({sites_filter}) "{kw}" after:2025-08-04 before:2025-08-25'
            payload = json.dumps({"q": dork_query, "num": 30})
            res = requests.post("https://google.serper.dev/search", headers=headers, data=payload)
            if res.status_code == 200:
                organic = res.json().get("organic", [])
                for item in organic:
                    link = item.get("link", "")
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    date_str = item.get("date", "ضمن نطاق البحث")
                    is_priority = False

                    # تحديد المنصة
                    platform = "Social Media"
                    if "tiktok.com" in link:
                        platform = "TikTok"
                        tt_date, unix_ts = decode_tiktok_timestamp(link)
                        if tt_date:
                            date_str = f"تاريخ الرفع الدقيق: {tt_date}"
                            # التحقق مما إذا كان قد رُفع بين 5 أغسطس 4 فجراً و 8 أغسطس
                            if 1754355600 <= unix_ts <= 1754697600:
                                is_priority = True
                            elif unix_ts < 1754355600:
                                # استبعاد الفيديوهات القديمة التي أُعيدت فهرستها بسبب تعليق جديد
                                continue
                    elif "instagram.com" in link:
                        platform = "Instagram Reel/Post"
                    elif "facebook.com" in link:
                        platform = "Facebook Video"
                    elif "vk.com" in link:
                        platform = "VK Video"
                    elif "x.com" in link or "twitter.com" in link:
                        platform = "X (Twitter)"

                    add_result(
                        url=link,
                        title=title,
                        platform=platform,
                        lang=lang,
                        published_at=date_str,
                        thumbnail="",
                        snippet=snippet,
                        priority=is_priority
                    )
            time.sleep(0.4)

def generate_html_report():
    """توليد لوحة تحكم HTML تفاعلية لعرض النتائج بوضوح"""
    sorted_items = sorted(
        results_db.values(),
        key=lambda x: (not x["priority"], x["published_at"]),
    )

    cards_html = ""
    for item in sorted_items:
        badge_color = "#16a34a" if item["priority"] else "#475569"
        priority_tag = '<span class="priority-badge">تطابق زمني عالي (5-7 أغسطس)</span>' if item["priority"] else ""
        thumb_html = f'<img src="{item["thumbnail"]}" loading="lazy" alt="thumb">' if item["thumbnail"] else '<div class="no-thumb">مقطع خارجي (اضغط للفتح)</div>'

        cards_html += f"""
        <div class="card {'priority-card' if item['priority'] else ''}" data-platform="{item['platform']}">
            {thumb_html}
            <div class="card-body">
                <div class="tags">
                    <span class="badge" style="background:{badge_color}">{item['platform']}</span>
                    <span class="badge lang">{item['lang']}</span>
                    {priority_tag}
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
        .header {{ max-width: 1200px; margin: 0 auto 25px; background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto; }}
        .card {{ background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; display: flex; flex-direction: column; }}
        .priority-card {{ border: 2px solid #22c55e; box-shadow: 0 0 15px rgba(34, 197, 94, 0.2); }}
        .card img {{ width: 100%; height: 180px; object-fit: cover; }}
        .no-thumb {{ width: 100%; height: 120px; background: #0f172a; display: flex; align-items: center; justify-content: center; color: #64748b; font-size: 14px; }}
        .card-body {{ padding: 15px; flex: 1; display: flex; flex-direction: column; }}
        .tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
        .badge {{ font-size: 12px; padding: 3px 8px; border-radius: 6px; color: white; }}
        .lang {{ background: #0284c7; }}
        .priority-badge {{ background: #dc2626; color: #fff; font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: bold; }}
        h3 {{ margin: 0 0 8px; font-size: 15px; line-height: 1.4; }}
        h3 a {{ color: #38bdf8; text-decoration: none; }}
        .date {{ font-size: 13px; color: #94a3b8; margin: 0 0 8px; font-weight: bold; }}
        .snippet {{ font-size: 13px; color: #cbd5e1; margin: 0 0 15px; flex: 1; }}
        .open-btn {{ text-align: center; background: #2563eb; color: white; text-decoration: none; padding: 8px; border-radius: 6px; font-size: 14px; font-weight: bold; }}
        .open-btn:hover {{ background: #1d4ed8; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>نتائج التنقيب عن فيديو الدفن في البقيع (الثلاثاء 5 أغسطس 2025 / 11 صفر 1447 هـ)</h2>
        <p>الإحداثيات المستهدفة: <code>24.466694, 39.614944</code> | إجمالي الفيديوهات المكتشفة: <strong>{len(results_db)}</strong></p>
        <p>البطاقات ذات الإطار الأخضر هي فيديوهات تم التأكد برمجياً أنها رُفعت في يوم 5 أغسطس 2025 أو اليومين التاليين له مباشرة.</p>
    </div>
    <div class="grid">
        {cards_html}
    </div>
</body>
</html>"""

    with open("results.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(list(results_db.values()), f, ensure_ascii=False, indent=2)
    print(f"[+] اكتمل التنقيب! تم حفظ {len(results_db)} نتيجة في results.html و results.json")

if __name__ == "__main__":
    search_youtube_geo()
    search_youtube_keywords()
    search_social_platforms()
    generate_html_report()
