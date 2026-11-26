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
        "out_keywords": ["售罄", "缺貨", "暫時缺貨", "敬請期待", "通知我"],
        "in_keywords": ["加入購物車", "立即購買", "訂購"]
    },
    {
        "store": "豐澤 Fortress",
        "type": "大型連鎖 (網購/門市)",
        "url": "https://www.fortress.com.hk/zh-hk/product/playstation-5-ps5-slim-%E6%95%B8%E4%BD%8D%E7%89%88%E4%B8%BB%E6%A9%9F-825gb-cfi-2118b01/p/BP_13989348?variant=13989348",
        "out_keywords": ["售罄", "暫時缺貨", "貨品已售罄", "無法購買", "到貨通知"],
        "in_keywords": ["加入購物車"]
    },
    {
        "store": "友和 YOHO",
        "type": "大型連鎖 (網購/門市)",
        "url": "https://www.yohohongkong.com/zh-hk/product/400737-%E7%B4%A2%E5%B0%BC-Sony-PlayStation-5-Slim-%E6%95%B8%E4%BD%8D%E7%89%88%E9%81%8A%E6%88%B2%E4%B8%BB%E6%A9%9F-CFI-2118B01-825GB-%E6%96%B0%E5%8C%85%E8%A3%9D-%E9%A6%99%E6%B8%AF%E8%A1%8C%E8%B2%A8",
        "out_keywords": ["缺貨", "售罄", "到貨通知"],
        "in_keywords": ["加入購物車", "立即購買"]
    },
    {
        "store": "OpenShop (2000Fun)",
        "type": "電玩連鎖 (網購/門市)",
        "url": "https://www.openshop.com.hk/product/30071",
        "out_keywords": ["售罄", "缺貨", "已售完"],
        "in_keywords": ["加入購物車", "立即購買"]
    },
    {
        "store": "Price.com.hk (行貨最低價參考)",
        "type": "全港格價參考",
        "url": "https://www.price.com.hk/product.php?p=602970",
        "out_keywords": ["沒有報價"],
        "in_keywords": ["安心訂購", "查詢", "HK$"]
    }
]

def extract_price(text):
    # 尋找 HK$ 3,500 ~ 9,999 區間的合理主機價格，排除配件或分期小字
    matches = re.findall(r'(?:HK\$|\$)\s*([3-9],\d{3}|[3-9]\d{3})', text)
    prices = [int(m.replace(',', '')) for m in matches if 3500 <= int(m.replace(',', '')) <= 9999]
    if not prices:
        return None
    # Price.com.hk 取最低行貨報價；單一網店取出現最多的主標價
    return min(prices)

def main():
    hk_tz = timezone(timedelta(hours=8))
    now_str = datetime.now(hk_tz).strftime("%Y-%m-%d %H:%M")

    old_prices = {}
    if os.path.exists("data.json"):
        try:
            with open("data.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for item in old_data.get("items", []):
                    if item.get("price"):
                        old_prices[item["store"]] = item["price"]
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
                page.wait_for_timeout(4000)  # 等待動態價格與庫存按鈕渲染

                body_text = page.inner_text("body")
                price = extract_price(body_text)

                if target["store"].startswith("Price.com.hk"):
                    status = "參考格價 (請留意店舖條款)"
                    is_available = True if price else False
                else:
                    # 嚴格檢查「加入購物車」按鈕是否真實存在且可點擊（破解假現貨）
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

            except Exception as e:
                note = "網頁載入逾時"
            finally:
                page.close()

            # 計算升帳與昨日差價
            premium = (price - MSRP) if price else None
            prev_p = old_prices.get(target["store"])
            daily_diff = (price - prev_p) if (price and prev_p) else 0

            results.append({
                "store": target["store"],
                "type": target["type"],
                "status": status,
                "is_available": is_available,
                "price": price,
                "msrp": MSRP,
                "premium": premium,
                "daily_diff": daily_diff,
                "url": target["url"],
                "note": note
            })

        browser.close()

    output = {
        "updated_at": now_str,
        "model": "PS5 Slim 數位版 (CFI-2118B01 / 825GB)",
        "msrp": MSRP,
        "items": results
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
