"""
台股常見公司名稱 → yfinance 代號對照表。
字典裡有的公司一律以此為準（蓋掉 Gemini 猜測的代號），沒有才 fallback 用 Gemini 給的值。
"""

_TW: dict[str, str] = {
    # 晶圓代工
    "台積電": "2330.TW", "TSMC": "2330.TW",
    "聯電": "2303.TW", "世界先進": "5347.TWO",
    # 記憶體
    "南亞科": "2408.TW", "華邦電": "2344.TW", "旺宏": "2337.TW",
    "力積電": "6770.TW",
    # 封裝測試
    "日月光": "3711.TW", "京元電": "2449.TW",
    "矽品": "3711.TW",   # 2024-04 與日月光合併下市，改列日月光投控
    "奇力新": "2327.TW", # 2022-01 下市，併入國巨 100% 子公司
    # IC 設計
    "聯發科": "2454.TW", "MediaTek": "2454.TW", "MTK": "2454.TW",
    "聯詠": "3034.TW", "瑞昱": "2379.TW", "奇景": "3533.TW",
    "矽統": "2363.TW", "立積": "4968.TW",
    # 被動元件
    "國巨": "2327.TW", "華新科": "2492.TW", "信昌電": "6173.TWO",
    # 伺服器 / 網通
    "廣達": "2382.TW", "緯創": "3231.TW", "英業達": "2356.TW",
    "仁寶": "2324.TW", "和碩": "4938.TW", "鴻海": "2317.TW",
    "緯穎": "6669.TW", "雲達": "6441.TWO",
    # 散熱 / 機構
    "奇鋐": "3017.TW", "雙鴻": "3324.TWO", "超眾": "6230.TW",
    # 光通訊
    "源傑": "6664.TWO", "波若威": "3163.TWO",
    # AI 伺服器相關
    "緯穎科技": "6669.TW",
    # 電源 / 離散元件
    "富鼎": "8261.TW",
    # 其他常見
    "台達電": "2308.TW", "研華": "2395.TW", "台光電": "2383.TW",
    "欣興": "3037.TW", "南電": "8046.TW", "景碩": "3189.TW",
    "台郡": "6269.TW", "譜瑞": "4966.TWO",
    # 上櫃股（.TWO）— 2026-07 資料稽核時確認過的常見誤植代號
    "群聯": "8299.TWO", "群聯電子": "8299.TWO",
    "穩懋": "3105.TWO", "穩懋半導體": "3105.TWO",
    "精材": "3374.TWO",
    "萬潤": "6187.TWO", "萬潤科技": "6187.TWO",
    "微創軟體": "7725.TWO",
    "信驊": "5274.TWO",
    "原相": "3227.TWO",
    "91APP": "6741.TWO",
    "騰雲": "6870.TWO",
    "璟德": "3152.TWO",
    "聯亞光電": "3081.TWO",
    "高技": "5439.TWO",
    "中裕新藥": "4147.TWO",
    "台燿": "6274.TWO",
    "茂達": "6138.TWO",
    "環球晶": "6488.TWO",
    "富喬": "1815.TWO",
    "昇達科": "3491.TWO",
    "合晶": "6182.TWO",
    "博智電子": "8155.TWO", "博智電子（ACCL）": "8155.TWO",
    "MACO": "6613.TWO",
    "金山電": "8042.TWO",
    "加弘": "6538.TWO",
    "笙泉": "3122.TWO",
}

_US: dict[str, str] = {
    "台積電ADR": "TSM", "TSMC ADR": "TSM",
    "輝達": "NVDA", "英偉達": "NVDA",
    "超微": "AMD", "AMD": "AMD",
    "英特爾": "INTC", "Intel": "INTC",
    "安森美": "ON", "onsemi": "ON",
    "德州儀器": "TXN", "TI": "TXN",
    "意法半導體": "STM", "ST": "STM",
    "英飛凌": "IFNNY", "Infineon": "IFNNY",
    "Vishay": "VSH", "威世": "VSH", "Vshare": "VSH",
    "Marvell": "MRVL", "邁威爾": "MRVL",
    "博通": "AVGO", "Broadcom": "AVGO",
    "高通": "QCOM", "Qualcomm": "QCOM",
    "蘋果": "AAPL", "Apple": "AAPL",
    "微軟": "MSFT", "Microsoft": "MSFT",
    "谷歌": "GOOGL", "Google": "GOOGL", "Alphabet": "GOOGL",
    "亞馬遜": "AMZN", "Amazon": "AMZN",
    "特斯拉": "TSLA", "Tesla": "TSLA",
    "Palantir": "PLTR", "波瀾坦": "PLTR",
    "Cloudflare": "NET",
    "CrowdStrike": "CRWD",
    "Palo Alto": "PANW",
    "Coherent": "COHR",
    "Lumentum": "LITE",
    "Micron": "MU", "美光": "MU",
    "AST SpaceMobile": "ASTS",
    "Arm": "ARM",
    "Enovis": "ENOV",
    "Applied Materials": "AMAT", "應用材料": "AMAT",
    "Teradyne": "TER",
    "Keysight": "KEYS",
    "Eaton": "ETN",
    "Axcelis": "ACLS",
    "SpaceX": "SPCX",       # 2026-06-12 IPO
    "Pure Storage": "P",    # 2026 改名 Everpure，代號原為 PSTG
    "Square": "XYZ", "Block": "XYZ",  # 原代號 SQ
}

_ALL = {**_TW, **_US}


def resolve(name: str, fallback: str = "Unknown") -> str:
    """用公司名稱查代號；查不到回傳 fallback。"""
    return _ALL.get(name, fallback)


def resolve_code(stock_name: str, current_code: str) -> str:
    """字典有紀錄的公司一律信字典（蓋掉 Gemini 猜測的代號，常見上市/上櫃尾綴搞混）；
    字典沒有才在 current_code 是 Unknown 時嘗試用名稱補齊。"""
    known = _ALL.get(stock_name)
    if known:
        return known
    if current_code and current_code != "Unknown":
        return current_code
    return resolve(stock_name, "Unknown")
