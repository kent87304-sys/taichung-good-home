#!/usr/bin/env python3
"""Download official MOI presale datasets and regenerate static website data."""
from __future__ import annotations
import csv, io, json, re, statistics, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISTRICTS = {"北屯區", "西屯區", "南屯區", "烏日區", "太平區"}
PRICE_URL = "https://plvr.land.moi.gov.tw/opendata/lvr_landBcsv.zip"
BUILDCASE_URL = "https://plvr.land.moi.gov.tw/opendata/lvr_buildcasecsv.zip"

def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "taichung-good-home/1.0"})
    with urllib.request.urlopen(req, timeout=90) as res:
        data = res.read()
    if len(data) < 1000:
        raise RuntimeError(f"download too small: {url}")
    return data

def zip_csv(blob: bytes, suffix: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(suffix)]
        if not names:
            raise RuntimeError(f"missing {suffix}")
        text = z.read(names[0]).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows[1:] if rows and rows[0].get("鄉鎮市區", "").upper() == "TOWN" else rows

def roc_date(value: str) -> str:
    value = (value or "").strip()
    return f"{value[:3]}/{value[3:5]}/{value[5:7]}" if len(value) >= 7 else value

def period_dates(text: str) -> list[int]:
    found = []
    for y, m, d in re.findall(r"(?<!\d)(1\d{2})\s*年?\s*[./-]?\s*(\d{1,2})\s*月?\s*[./-]?\s*(\d{1,2})\s*日?", text):
        found.append(int(y) * 10000 + int(m) * 100 + int(d))
    found += [int(x) for x in re.findall(r"(?<!\d)(1\d{6})(?!\d)", text)]
    return found

def sale_status(period: str, today_roc: int) -> str:
    dates = period_dates(period)
    if dates and min(dates) > today_roc: return "尚未開售"
    if ("完銷" in period or "銷售完畢" in period) and not any(x < today_roc for x in dates[1:]): return "銷售中（至完銷）"
    if len(dates) >= 2 and max(dates) < today_roc: return "銷售期間已結束"
    if dates and min(dates) <= today_roc and (len(dates) == 1 or max(dates) >= today_roc): return "銷售中"
    return "狀態未明"

def main() -> None:
    price_rows = zip_csv(download(PRICE_URL), "b_lvr_land_b.csv")
    build_rows = zip_csv(download(BUILDCASE_URL), "b_lvr_buildcase.csv")
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in price_rows:
        if r.get("鄉鎮市區") not in DISTRICTS or r.get("解約情形"): continue
        district = r["鄉鎮市區"].removesuffix("區")
        name = (r.get("建案名稱") or "").strip()
        location = (r.get("土地位置建物門牌") or "").replace("臺中市" + r["鄉鎮市區"], "").strip()
        location = re.sub(r"\d+號.*$", "", location).strip() or "地址去識別化"
        key_name = name or f"{location}｜名稱未揭露"
        try:
            unit = round(float(r["單價元平方公尺"]) * 3.305785 / 10000, 1)
            total = round(float(r["總價元"]) / 10000)
            area = round(float(r["建物移轉總面積平方公尺"]) / 3.305785, 1)
            parking = round(float(r.get("車位總價元") or 0) / 10000)
        except (ValueError, TypeError, KeyError):
            continue
        grouped[(district, key_name)].append({"date": roc_date(r.get("交易年月日", "")), "unit": unit, "total": total, "rooms": r.get("建物現況格局-房") or "未揭露", "area": area, "parking": parking})
    if len(grouped) < 10: raise RuntimeError("too few Taichung project groups")
    district_units: dict[str, list[float]] = defaultdict(list)
    for (district, _), xs in grouped.items(): district_units[district] += [x["unit"] for x in xs]
    district_median = {d: statistics.median(v) for d, v in district_units.items()}
    colors = ["sage", "clay", "blue", "sand", "plum"]
    projects = []
    for idx, ((district, name), xs) in enumerate(sorted(grouped.items())):
        units, totals, areas = [x["unit"] for x in xs], [x["total"] for x in xs], [x["area"] for x in xs]
        rooms = sorted({x["rooms"] for x in xs if x["rooms"].isdigit() and x["rooms"] != "0"}, key=int)
        room_label = f"{rooms[0]}–{rooms[-1]} 房" if len(rooms) > 1 else (f"{rooms[0]} 房" if rooms else "格局未揭露")
        median = round(statistics.median(units), 1); diff = round((median / district_median[district] - 1) * 100, 1)
        if diff <= -8: deal = ("價格機會佳", "good", 90)
        elif diff <= -3: deal = ("值得優先比較", "watch", 78)
        elif diff <= 5: deal = ("接近區域行情", "fair", 65)
        else: deal = ("高於區域行情", "high", 45)
        projects.append({"id": idx + 1, "name": name, "district": district, "area": "政府實登建案", "builder": "待與建案備查核對", "score": len(xs), "trust": 0, "price": median, "fairLow": min(units), "fairHigh": max(units), "total": f"中位數 {round(statistics.median(totals)):,} 萬", "rooms": room_label, "size": f"{min(areas):.1f}–{max(areas):.1f} 坪", "eta": "本期資料", "tags": ["政府資料", f"{len(xs)} 筆揭露", "實價登錄"], "reason": f"內政部本期預售實價資料；整理 {len(xs)} 筆成交。", "risk": "仍需核對樓層、車位、付款條件與契約賣方。", "color": colors[idx % len(colors)], "latest": max(x["date"] for x in xs), "transactions": sorted(xs, key=lambda x: x["date"], reverse=True), "districtMedian": round(district_median[district], 1), "priceDiff": diff, "dealLabel": deal[0], "dealLevel": deal[1], "dealScore": deal[2], "sourceLevel": "政府確認＋網站計算"})
    tz = timezone(timedelta(hours=8)); now = datetime.now(tz); today_roc = (now.year - 1911) * 10000 + now.month * 100 + now.day
    # price lookup by district/name and street
    name_price = {(p["district"], p["name"]): p for p in projects}
    launches = []
    for idx, r in enumerate(build_rows):
        if r.get("鄉鎮市區") not in DISTRICTS: continue
        district = r["鄉鎮市區"].removesuffix("區"); name = (r.get("建案名稱") or "建案名稱未揭露").strip()
        matched = name_price.get((district, name)); period = r.get("銷售期間") or "政府資料未提供"
        launches.append({"id": idx + 1, "name": name, "district": district, "street": r.get("坐落街道") or "坐落街道未揭露", "builder": r.get("起造人") or "起造人未揭露", "filingDate": roc_date(r.get("申報備查日期", "")), "salesPeriod": period, "status": sale_status(period, today_roc), "avgPrice": matched["price"] if matched else None, "matchCount": matched["score"] if matched else 0})
    launches.sort(key=lambda x: x["filingDate"], reverse=True); launches = launches[:300]
    bgroups: dict[str, list[dict]] = defaultdict(list)
    for x in launches:
        name = re.sub(r"負責人[：:].*", "", x["builder"]).strip() or "起造人未揭露"; bgroups[name].append(x)
    builders = []
    for name, xs in bgroups.items():
        clarity = round(sum(x["status"] != "狀態未明" for x in xs) / len(xs) * 100)
        risk = "red" if name == "起造人未揭露" else ("green" if clarity >= 80 and len(xs) >= 2 else "yellow")
        builders.append({"name": name, "filingCount": len(xs), "activeCount": sum(x["status"].startswith("銷售中") for x in xs), "endedCount": sum(x["status"] == "銷售期間已結束" for x in xs), "clarity": clarity, "risk": risk, "label": "資料不足" if risk == "red" else ("官方資料較完整" if risk == "green" else "待補強核對"), "source": "內政部預售屋建案備查"})
    builders.sort(key=lambda x: x["filingCount"], reverse=True)
    outputs = {"government-data.js": "window.GOVERNMENT_PROJECTS=" + json.dumps(projects, ensure_ascii=False, separators=(",", ":")) + ";\n", "launch-data.js": "window.GOVERNMENT_LAUNCHES=" + json.dumps(launches, ensure_ascii=False, separators=(",", ":")) + ";\n", "builder-data.js": "window.GOVERNMENT_BUILDERS=" + json.dumps(builders, ensure_ascii=False, separators=(",", ":")) + ";\n", "data-meta.js": "window.DATA_META=" + json.dumps({"updatedAt": now.strftime("%Y-%m-%d %H:%M"), "projectCount": len(projects), "transactionCount": sum(len(p.get("transactions", [])) for p in projects), "launchCount": len(launches), "builderCount": len(builders), "source": "內政部地政司"}, ensure_ascii=False) + ";\n"}
    for name, content in outputs.items():
        tmp = ROOT / (name + ".tmp"); tmp.write_text(content, encoding="utf-8"); tmp.replace(ROOT / name)
    print(f"updated {len(projects)} projects, {len(launches)} launch records, {len(builders)} builders")

if __name__ == "__main__": main()
