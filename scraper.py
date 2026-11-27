import json
import os
import re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

MSRP = 4257  # PS5 Slim 數位版 (CFI-2118B01) 香港官方建議零售價

TARGETS = [
    {
        "store": "Sony Store 官方網店",
        "type": "官方直營",
        "url": "https://www.sony.com.hk/product/details/productpage.jsp?modelCode=27446186&lang=zh",
        "in_keywords": ["加入購物車", "立即購買", "訂購"]
    },
    {
        "store": "豐澤 Fortress",
        "type": "大型連鎖 (網購/門市)",
        "url": "https://www.fortress.com.hk/zh-hk/product/playstation-5-ps5-slim-%E6%95%B8%E4%BD%8D%E7%89%88%E4%B8%BB%E6%A9%9F-825gb-cfi-2118b01/p/BP_13989348?variant=13989348",
        "in_keywords": ["加入購物車"]
    },
    {
        "store": "友和 YOHO",
        "type": "大型連鎖 (網購/門市)",
        "url": "https://www.yohohongkong.com/zh-hk/product/400737-%E7%B4%A2%E5%B0%BC-Sony-PlayStation-5-Slim-%E6%95%B8%E4%BD%8D%E7%89%88%E9%81%8A%E6%88%B2%E4%B8%BB%E6%A9%9F-CFI-2118B01-825GB-%E6%96%B0%E5%8C%85%E8%A3%9D-%E9%A6%99%E6%B8%AF%E8%A1%8C%E8%B2%A8",
        "in_keywords": ["加入購物車", "立即購買"]
    },
    {
        "store": "OpenShop (2000Fun)",
        "type": "電玩連鎖 (網購/門市)",
        "url": "https://www.openshop.com.hk/product/30071",
        "in_keywords": ["加入購物車", "立即購買"]
    },
    {
        "store": "Price.com.hk (行貨最低價參考)",
        "type": "全港格價參考",
        "url": "https://www.price.com.hk/product.php?p=602970",
        "in_keywords": ["安心訂購", "查詢", "HK$"]
    }
]

def extract_price(text):
    matches = re.findall(r'(?:HK\$|\$)\s*([3-9],\d{3}|[3-9]\d{3})', text)
    prices = [int(m.replace(',', '')) for m in matches if 3500 <= int(m.replace(',', '')) <= 9999]
    if not prices:
        return None
    return min(prices)

def main():
    hk_tz = timezone(timedelta(hours=8))
    now_str = datetime.now(hk_tz).strftime("%Y-%m-%d %H:%M")

    # 讀取前一次抓到的價格與上次更新時間
    prev_records = {}
    prev_updated_at = None
    if os.path.exists("data.json"):
        try:
            with open("data.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
                prev_updated_at = old_data.get("updated_at")
                for item in old_data.get("items", []):
                    prev_records[item["store"]] = {
                        "price": item.get("price"),
                        "prev_price": item.get("prev_price"),
                        "last_diff": item.get("last_diff")
                    }
        except Exception:
            pass

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="zh-HK"
        )

        for target in TARGETS:
            page = context.new_page()
            status = "檢查失敗/需人工確認"
            is_available = False
            price = None
            note = ""

            try:
                page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4000)

                body_text = page.inner_text("body")
                price = extract_price(body_text)

                if target["store"].startswith("Price.com.hk"):
                    status = "參考格價 (請留意店舖條款)"
                    is_available = True if price else False
                else:
                    has_active_btn = False
                    for kw in target["in_keywords"]:
                        btns = page.locator(f"button:has-text('{kw}'), a:has-text('{kw}')")
                        count = btns.count()
                        for i in range(count):
                            btn = btns.nth(i)
                            if btn.is_visible():
                                disabled = btn.get_attribute("disabled")
                                cls = (btn.get_attribute("class") or "").lower()
                                if disabled is None and "disabled" not in cls and "sold" not in cls:
                                    has_active_btn = True
                                    break
                        if has_active_btn:
                            break

                    if has_active_btn:
                        status = "✅ 真現貨 (可落單/自取)"
                        is_available = True
                    else:
                        status = "❌ 暫時無貨 / 假現貨過濾"
                        is_available = False

            except Exception:
                note = "網頁載入逾時"
            finally:
                page.close()

            # 對比「上一次成功抓到的價格」計算每次刷新的升跌
            prev_info = prev_records.get(target["store"], {})
            last_recorded_price = prev_info.get("price")

            if price is not None and last_recorded_price is not None:
                prev_price_used = last_recorded_price
                last_diff = price - last_recorded_price
            else:
                prev_price_used = prev_info.get("prev_price")
                last_diff = prev_info.get("last_diff") if price is None else None

            premium = (price - MSRP) if price is not None else None

            results.append({
                "store": target["store"],
                "type": target["type"],
                "status": status,
                "is_available": is_available,
                "price": price,
                "prev_price": prev_price_used,
                "msrp": MSRP,
                "premium": premium,
                "last_diff": last_diff,
                "url": target["url"],
                "note": note
            })

        browser.close()

    output = {
        "updated_at": now_str,
        "prev_updated_at": prev_updated_at,
        "model": "PS5 Slim 數位版 (CFI-2118B01 / 825GB)",
        "msrp": MSRP,
        "items": results
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
