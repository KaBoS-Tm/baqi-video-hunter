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

# النطاقات الزمنية
SQUARE_START_ISO = "2025-08-04T00:00:00Z"
SQUARE_END_ISO = "2025-08-09T23:59:59Z"
END_DATE_ISO = "2025-08-28T23:59:59Z"

# تنظيف المفاتيح تلقائياً من أي مسافات زائدة أثناء النسخ واللصق
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()

api_status = {
    "youtube": "غير مفعل",
    "serper": "غير مفعل",
    "snapmap": "جاهز"
}

# مصفوفة اللغات الشاملة (بدون تعقيد يمنع ظهور النتائج)
BURIAL_QUERIES = {
    "Arabic": [
        "دفن في البقيع", "مقبرة البقيع دفن", "جنازة البقيع", "بقيع الغرقد دفن",
        "البقيع بعد الفجر", "دفن موتى البقيع", "البقيع 11 صفر", "البقيع 5 أغسطس",
        "سناب البقيع", "تصوير البقيع"
    ],
    "Indonesian_Malay": [
        "pemakaman baqi", "pemakaman di baqi madinah", "makam baqi", "kuburan baqi",
        "jannatul baqi pemakaman", "penguburan baqi", "jenazah di baqi", "pengebumian baqi"
    ],
    "Urdu_Hindi": [
        "جنت البقیع تدفین", "جنت البقیع قبرستان", "بقیع میں تدفین", "جنت البقیع جنازہ",
        "jannatul baqi burial", "jannat ul baqi qabristan", "baqi madinah janaza"
    ],
    "Turkish": [
        "cennetül baki defin", "baki mezarlığı cenaze", "medine baki kabristanı", "cennetül baki cenaze"
    ],
    "Russian_CentralAsia": [
        "кладбище баки похороны", "джаннат аль баки", "baqi qabristoni", "jannatul baqi dafn",
        "бақи зираты", "қабристони бақеъ"
    ],
    "Bengali": [
        "জান্নাতুল বাকি দাফন", "মদিনা জান্নাতুল বাকি", "জান্নাতুল বাকি কবরস্থান"
    ],
    "Persian_Pashto": [
        "دفن در بقیع", "قبرستان بقیع تدفین", "جنت البقیع مدینه", "جنت البقيع هديره"
    ],
    "English_French_African": [
        "jannatul baqi burial", "al baqi cemetery burial", "burying in baqi madinah",
        "enterrement baqi médine", "cimetière al baqi", "makaburi ya baqi"
    ]
}

CORE_BAQI_TERMS = [
    "مقبرة البقيع", "بقيع الغرقد", "البقيع", "jannatul baqi", "pemakaman baqi",
    "جنت البقیع", "cennetül baki", "кладбище баки", "baqi qabristoni", "জান্নাতুল বাকি"
]

# قائمة المنصات الثابتة لضمان ظهور أزرارها دائماً في الصفحة
ALL_PLATFORMS_ORDER = [
    "YouTube", "TikTok", "Snapchat", "Instagram", "Facebook",
    "VK", "Telegram", "X", "Dailymotion", "Likee_Kwai", "Other"
]

results_db = {}

def load_previous_results():
    """تحميل النتائج السابقة من الذاكرة التراكمية"""
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
    if "tiktok.com" in u: return "TikTok"
    if "snapchat.com" in u: return "Snapchat"
    if "instagram.com" in u: return "Instagram"
    if "facebook.com" in u or "fb.watch" in u: return "Facebook"
    if "vk.com" in u or "ok.ru" in u: return "VK"
    if "t.me/" in u or "telegram.me" in u: return "Telegram"
    if "x.com" in u or "twitter.com" in u: return "X"
    if "dailymotion.com" in u: return "Dailymotion"
    if "likee.video" in u or "kwai.com" in u or "threads.net" in u: return "Likee_Kwai"
    if "youtube.com" in u or "youtu.be" in u: return "YouTube"
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
        "6 أغسطس", "7 أغسطس"
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

def search_snap_map_direct():
    """1. فحص خريطة سناب شات المباشرة (Snap Map Web API) حول إحداثيات القبر"""
    print("[*] جاري فحص خريطة سناب شات المباشرة (Snap Map) حول إحداثيات البقيع...")
    try:
        epoch_res = requests.post(
            "https://ms.sc-jpl.com/web/getLatestTileSet",
            json={},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        epoch = "0"
        if epoch_res.status_code == 200:
            infos = epoch_res.json().get("tileSetInfos", [])
            for info in infos:
                if info.get("id", {}).get("type") == "HEAT":
                    epoch = info.get("id", {}).get("epoch", "0")
                    break

        playlist_payload = {
            "requestGeoPoint": {"lat": LAT, "lon": LON},
            "zoomLevel": 17.5,
            "tileSetId": {"flavor": "default", "epoch": epoch, "type": "HEAT"},
            "radiusMeters": 600.0,
            "maximumFuzzRadius": 0
        }
        pl_res = requests.post(
            "https://ms.sc-jpl.com/web/getPlaylist",
            json=playlist_payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if pl_res.status_code == 200:
            elements = pl_res.json().get("manifest", {}).get("elements", [])
            api_status["snapmap"] = f"متصل ({len(elements)} قصة نشطة بالموقع)"
            for el in elements:
                snap_id = el.get("id", "")
                ts_ms = int(el.get("timestamp", 0))
                 unix_ts = ts_ms // 1000 if ts_ms else 0
                dt_str = datetime.fromtimestamp(unix_ts, tz=AST_TZ).strftime("%Y-%m-%d %H:%M:%S") if unix_ts else "خريطة السناب"
                media_info = el.get("snapInfo", {}).get("streamingMediaInfo", {})
                thumb = media_info.get("previewUrl", "")
                snap_url = f"https://map.snapchat.com/@{LAT},{LON},18.00z"
                if snap_id:
                    add_result(
                        f"{snap_url}#snap={snap_id}",
                        f"قصة خريطة سناب شات من داخل نطاق البقيع ({snap_id[:8]})",
                        "Snapchat",
                        "Snap Map إحداثيات",
                        dt_str,
                        thumb,
                        "تم التقاطها من رادار خريطة سناب شات فوق إحداثيات البقيع",
                        classify_tier(dt_str, unix_ts)
                    )
        else:
            api_status["snapmap"] = f"رمز الاتصال {pl_res.status_code}"
    except Exception as e:
        api_status["snapmap"] = "فحص الويب البديل"
        print(f"[!] تنبيه Snap Map المباشر: {e}")

def search_dailymotion_direct():
    """2. فحص محرك Dailymotion الرسمي المباشر بالتاريخ الدقيق (بدون مفتاح)"""
    print("[*] جاري فحص منصة Dailymotion المباشر...")
    # من 4 أغسطس إلى 28 أغسطس 2025 بالثواني
    created_after = 1754254800
    created_before = 1756425599
    for term in ["baqi", "البقيع", "بقيع", "baki", "بقیع", "madinah", "المدينة المنورة"]:
        try:
            params = {
                "search": term,
                "created_after": created_after,
                "created_before": created_before,
                "limit": 50,
                "fields": "id,title,description,url,thumbnail_480_url,created_time"
            }
            res = requests.get("https://api.dailymotion.com/videos", params=params, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("list", []):
                    c_time = int(item.get("created_time", 0))
                    dt_str = datetime.fromtimestamp(c_time, tz=AST_TZ).strftime("%Y-%m-%d %H:%M") if c_time else "أغسطس 2025"
                    add_result(
                        item.get("url"),
                        item.get("title"),
                        "Dailymotion",
                        f"بحث مباشر ({term})",
                        dt_str,
                        item.get("thumbnail_480_url", ""),
                        item.get("description", ""),
                        classify_tier(dt_str, c_time)
                    )
        except Exception as e:
            print(f"[!] خطأ Dailymotion: {e}")
        time.sleep(0.2)

def search_youtube_all():
    """3. مسح يوتيوب بالإحداثيات ومصفوفة اللغات"""
    if not YOUTUBE_API_KEY:
        api_status["youtube"] = "❌ المفتاح غير موجود"
        return

    api_status["youtube"] = "✅ متصل ويعمل"
    print("[*] جاري مسح يوتيوب بالإحداثيات واللغات...")
    for radius in ["300m", "800m", "2000m"]:
        params = {
            "part": "snippet", "type": "video",
            "location": LAT_LON, "locationRadius": radius,
            "publishedAfter": SQUARE_START_ISO, "publishedBefore": END_DATE_ISO,
            "maxResults": 50, "order": "date", "key": YOUTUBE_API_KEY
        }
        res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
        if res.status_code == 200:
            for item in res.json().get("items", []):
                vid_id = item["id"]["videoId"]
                snip = item["snippet"]
                pub = snip.get("publishedAt", "")
                thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                add_result(
                    f"https://www.youtube.com/watch?v={vid_id}",
                    snip.get("title"), "YouTube", f"إحداثيات ({radius})",
                    pub, thumb, snip.get("description", ""), classify_tier(pub)
                )
        elif res.status_code != 200:
            api_status["youtube"] = f"⚠️ تنبيه ({res.status_code})"

    for lang, keywords in BURIAL_QUERIES.items():
        for kw in keywords:
            params = {
                "part": "snippet", "type": "video", "q": kw,
                "publishedAfter": SQUARE_START_ISO, "publishedBefore": END_DATE_ISO,
                "maxResults": 50, "order": "date", "key": YOUTUBE_API_KEY
            }
            res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params)
            if res.status_code == 200:
                for item in res.json().get("items", []):
                    vid_id = item["id"]["videoId"]
                    snip = item["snippet"]
                    pub = snip.get("publishedAt", "")
                    thumb = snip.get("thumbnails", {}).get("high", {}).get("url", "")
                    add_result(
                        f"https://www.youtube.com/watch?v={vid_id}",
                        snip.get("title"), "YouTube", lang,
                        pub, thumb, snip.get("description", ""), classify_tier(pub)
                    )
            time.sleep(0.15)

def serper_request(query, label, tbs=None, endpoint="search"):
    """إرسال طلب نظيف ومباشر إلى Serper بدون أقواس معقدة"""
    if not SERPER_API_KEY:
        return 0
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload_dict = {"q": query, "num": 40}
    if tbs:
        payload_dict["tbs"] = tbs

    count_added = 0
    try:
        res = requests.post(f"https://google.serper.dev/{endpoint}", headers=headers, json=payload_dict, timeout=15)
        if res.status_code == 200:
            api_status["serper"] = "✅ متصل ويعمل"
            data = res.json()
            items = data.get("organic", []) if endpoint == "search" else data.get("videos", [])
            for item in items:
                link = item.get("link", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                date_str = item.get("date", "أغسطس 2025")
                thumb = item.get("imageUrl", "")
                unix_ts = 0
                platform = detect_platform_name(link)

                if platform == "TikTok":
                    tt_date, unix_ts = decode_tiktok_timestamp(link)
                    if tt_date:
                        date_str = f"وقت الرفع الدقيق: {tt_date}"
                        # نقبل الفيديوهات من أول أغسطس 2025 فصاعداً
                        if unix_ts < 1754000000:
                            continue

                tier = classify_tier(f"{date_str} {title} {snippet}", unix_ts)
                add_result(link, title, platform, label, date_str, thumb, snippet, tier)
                count_added += 1
        else:
            api_status["serper"] = f"❌ خطأ مفتاح Serper (رمز {res.status_code})"
            print(f"[!] خطأ من Serper رمز {res.status_code}: {res.text[:120]}")
    except Exception as e:
        print(f"[!] استثناء في اتصال Serper: {e}")
    return count_added

def search_all_social_deep():
    """4. المسح المفصول والعميق لكل منصة (TikTok, Snapchat, Instagram, FB, VK, Telegram, X, Likee)"""
    if not SERPER_API_KEY:
        api_status["serper"] = "❌ المفتاح غير مضاف في Secrets"
        print("[!] SERPER_API_KEY غير موجود!")
        return

    print("[*] جاري المسح العميق لمنصات التواصل عبر Serper...")
    # نطاق شهر أغسطس وسبتمبر 2025 في جوجل
    aug_tbs = "cdr:1,cd_min:8/3/2025,cd_max:9/5/2025"

    # أ) تقنية صيد البصمة الزمنية لتيك توك (أرقام 7534 و 7535 و 7536 تعني 3-9 أغسطس 2025 حتمياً)
    print("[*] تشغيل رادار البصمة الزمنية لتيك توك (7534 / 7535 / 7536)...")
    for prefix in ["7534", "7535", "7536"]:
        for term in CORE_BAQI_TERMS:
            q = f"site:tiktok.com inurl:{prefix} {term}"
            serper_request(q, f"بصمة تيك توك ({prefix})", tbs=None)
            time.sleep(0.2)

    # ب) مسح كل منصة على حدة باستعلام بسيط ونظيف بدون أقواس معقدة
    single_sites = [
        ("TikTok", "site:tiktok.com"),
        ("Snapchat", "site:snapchat.com"),
        ("Instagram", "site:instagram.com"),
        ("Facebook", "site:facebook.com"),
        ("VK", "site:vk.com"),
        ("Telegram", "site:t.me"),
        ("X", "site:x.com"),
        ("Likee_Kwai", "site:likee.video"),
        ("Likee_Kwai", "site:kwai.com")
    ]

    for plat_name, site_op in single_sites:
        print(f"[*] فحص منصة {plat_name} بشكل منفصل...")
        for term in CORE_BAQI_TERMS:
            # 1. بحث مفلتر بتاريخ أغسطس 2025
            serper_request(f"{site_op} {term}", f"{plat_name} (أغسطس)", tbs=aug_tbs)
            time.sleep(0.2)
            # 2. بحث بكلمة 2025 لاقتناص الفيديوهات التي لم يؤرشف جوجل تاريخها
            serper_request(f"{site_op} {term} 2025", f"{plat_name} (شامل)", tbs=None)
            time.sleep(0.2)

    # ج) مسح كلمات الدفن بجميع اللغات في تيك توك وإنستغرام وفيسبوك وسناب شات
    for lang, keywords in BURIAL_QUERIES.items():
        for kw in keywords:
            for site_op in ["site:tiktok.com", "site:instagram.com", "site:facebook.com", "site:snapchat.com", "site:vk.com", "site:t.me"]:
                serper_request(f"{site_op} {kw}", lang, tbs=aug_tbs)
                time.sleep(0.18)

def generate_html_report():
    """بناء لوحة النتائج مع أزرار ثابتة لجميع المنصات وخريطة سناب شات المباشرة"""
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

    # إظهار أزرار جميع المنصات بشكل دائم مع تمييز المنصات التي تحتوي على نتائج
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
            <span>📡 YouTube API: <strong>__YT_STATUS__</strong></span>
            <span>🌐 Serper Multi-Platform API: <strong>__SERPER_STATUS__</strong></span>
            <span>👻 رادار Snap Map: <strong>__SNAP_STATUS__</strong></span>
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
    print(f"[+] اكتمل التحديث الشامل! الإجمالي الآن: {len(results_db)} نتيجة (منها {new_count} جديدة).")

if __name__ == "__main__":
    load_previous_results()
    search_snap_map_direct()
    search_dailymotion_direct()
    search_youtube_all()
    search_all_social_deep()
    generate_html_report()
