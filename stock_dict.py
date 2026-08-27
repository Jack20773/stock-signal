"""
台股常見公司名稱 → yfinance 代號對照表。
字典裡有的公司一律以此為準（蓋掉 Gemini 猜測的代號），沒有才 fallback 用 Gemini 給的值。

2026-08-24 索羅門分身增修（來源：serenity-clone 回測實測抓到的資料 bug）：
1. 新增 `normalize_tw_suffix()`——用官方上市/上櫃名單校正 `.TW` / `.TWO` 後綴。
   根因：`prompt.py` 舊版的 schema 說明只寫「台股請附帶 .TW」，Gemini 因此把上櫃股
   一律標成 `.TW`，yfinance 一根 K 棒都抓不到（DB 實測：105 個 .TW 代號裡 19 個是上櫃）。
2. 新增 `resolve_by_official_name()`——本字典查不到時，先拿公司中文全名去官方名單反查，
   再退回 Gemini 猜的代號。
3. 刪掉 5 筆**指向別家公司**的錯誤條目（見下方 `# [2026-08-24 移除]` 註記）。
   這類錯誤比「查不到」危險得多：抓得到價、不會報錯，但算的是另一家公司。
白名單資料檔：`tw_listing_map.json`（由 `refresh_tw_listing_map.py` 從證交所／櫃買中心
open API 產生）。
"""
import json
import logging
from pathlib import Path

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
    "聯詠": "3034.TW", "瑞昱": "2379.TW",
    "矽統": "2363.TW", "立積": "4968.TW",
    # [2026-08-24 移除] "奇景": "3533.TW" —— 3533 是「嘉澤」(Lotes)，不是奇景。
    # 奇景光電只有美國 ADR，已改列 _US 的 "奇景": "HIMX"。
    # 被動元件
    "國巨": "2327.TW", "華新科": "2492.TW", "信昌電": "6173.TWO",
    # 伺服器 / 網通
    "廣達": "2382.TW", "緯創": "3231.TW", "英業達": "2356.TW",
    "仁寶": "2324.TW", "和碩": "4938.TW", "鴻海": "2317.TW",
    "緯穎": "6669.TW",
    # [2026-08-24 移除] "雲達": "6441.TWO" —— 6441 是「廣錠」(iBase Solution)，
    # 不是雲達；雲達科技(QCT)是廣達 100% 子公司，本身沒有單獨掛牌。
    # 散熱 / 機構
    "奇鋐": "3017.TW", "雙鴻": "3324.TWO", "超眾": "6230.TW",
    # 光通訊
    "波若威": "3163.TWO",
    # [2026-08-24 移除] "源傑": "6664.TWO" —— 6664 是「群翊」(Group Up Industrial)，
    # 不是源傑；源杰科技掛在上海科創板 688498，yfinance 的 .TW/.TWO 名稱空間裡沒有它。
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
    # [2026-08-24 移除] "微創軟體": "7725.TWO" —— 7725.TWO 在 yfinance 是
    # LabTurbo Biotech，且 7725 不在證交所/櫃買中心的名單裡；微創軟體未上市櫃。
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
    # [2026-08-24 移除] "MACO": "6613.TWO" —— 6613 是「朋億」(Nova Technology)，
    # 與 MACO 對不上；MACO 的正確標的未查證出來，寧可讓它落回 Unknown 也不掛錯家。
    "金山電": "8042.TWO",
    # [2026-08-24 移除] "加弘": "6538.TWO" —— 6538 是「倉和」(Brave C&H Supply)，不是加弘。
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
    "奇景": "HIMX", "奇景光電": "HIMX", "Himax": "HIMX",  # 2026-08-24 從 _TW 誤植的 3533.TW 移正
}

# 2026-08-28 新增：日股代號與台股 6000-6999 號段撞號的資料正確性 bug。
# 根因：Gemini 常把日股寫成 `代號.TW`（見 prompt.py Rule 7 註解），這兩個名字
# 若不在字典裡，resolve_code() 就會走到 fallback 分支，對 current_code 呼叫
# normalize_tw_suffix()——它只查後綴合不合官方名單，不知道這串數字其實是日股，
# 於是把 `6146.TW` 「校正」成 `6146.TWO`（=耕興 Sporton，真台股），
# 而 `6861.TW` 因為官方名單裡剛好也有一檔真台股 6861（=睿生光電）連校正都不用做
# 就直接放行——兩種都全流程零告警，抓得到真價、算得出績效，但算的是別家公司。
# 實跑重現：`resolve_code('DISCO','6146.TW')` → 修前 `6146.TWO`（耕興），
# `resolve_code('Keyence','6861.TW')` → 修前 `6861.TW`（睿生光電）。
# 把正確代號（.T 後綴，4 碼日股格式）放進字典，resolve_code() 第一層 `_lookup()`
# 就會先命中，直接跳過會誤判的 fallback。正確代號來源：prompt.py Rule 7 本身的
# 範例（`DISCO 6146.T`、`Keyence 6861.T`）。
# ⚠️ 只涵蓋這兩檔實測撞號、且是本次 bug 直接指名重現的案例，不是日股名稱的
# 全面盤點——語料裡還有沒有其他日股名字會撞號未知，見 project_stocksignal.md
# 「待裁決⑥後半」（prompt.py Rule 7 教 Gemini 外國股格式，尚待丹尼爾點頭）。
_JP: dict[str, str] = {
    "DISCO": "6146.T", "迪思科": "6146.T",
    "Keyence": "6861.T", "基恩斯": "6861.T",
}

_ALL = {**_TW, **_US, **_JP}
# 只補「前後空白」這種確定安全的正規化，不做同義詞/別名猜測（那需要業務知識判斷，
# 猜錯會把 A 公司誤配到 B 的代號，比查不到更糟）。原字典 key 不動，另建一份
# 「去空白後的 key → 原代號」的查表當 fallback：Gemini 回傳的公司名稱偶爾夾帶
# 前後空白（例如 "台積電 "），完全比對會直接跳過字典、退回不可靠的 Gemini 猜測
# 代號——2026-08-01 Codex 審查發現，索羅門本地修正。
_ALL_STRIPPED = {name.strip(): code for name, code in _ALL.items() if name.strip() != name}


# ---------------------------------------------------------------------------
# 官方上市/上櫃白名單（2026-08-24 新增）
# ---------------------------------------------------------------------------
# 資料檔由 refresh_tw_listing_map.py 從證交所 + 櫃買中心 open API 產生。
# 讀不到就退化成「什麼都不校正」——白名單是**加分項**，不該因為檔案缺席就讓
# 整條分析管線寫不進訊號（與 database._current_rule_version() 同一個設計原則）。
_LISTING_PATH = Path(__file__).with_name("tw_listing_map.json")


def _load_listing() -> tuple[dict[str, str], dict[str, str]]:
    try:
        raw = json.loads(_LISTING_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- 見上方註解：缺檔就不校正，不擋寫入
        logging.warning("[stock_dict] 讀不到 %s，本次不做上市/上櫃後綴校正", _LISTING_PATH.name)
        return {}, {}
    listing: dict[str, str] = raw.get("listing", {})
    # 官方名稱 → 代號的反查表。名稱帶 `*`（處置股註記）先剝掉。
    # 同名對到兩個以上代號的一律丟棄——寧可查不到，也不要在兩家公司之間亂猜。
    buckets: dict[str, set[str]] = {}
    for num, name in raw.get("names", {}).items():
        key = name.replace("*", "").strip()
        if key:
            buckets.setdefault(key, set()).add(num)
    by_name = {
        key: f"{next(iter(nums))}.{listing.get(next(iter(nums)), 'TW')}"
        for key, nums in buckets.items() if len(nums) == 1
    }
    return listing, by_name


_LISTING, _OFFICIAL_BY_NAME = _load_listing()


def normalize_tw_suffix(code: str) -> str:
    """把台股代號的 `.TW` / `.TWO` 後綴校正成官方歸屬（上市 .TW／上櫃 .TWO）。

    這是本次 bug 的正面攔截點：Gemini 標代號時傾向一律用 `.TW`，上櫃股因此
    yfinance 一根 K 棒都抓不到（DB 實測 105 個 .TW 代號裡 19 個其實是上櫃）。

    **白名單沒收錄的代號一律原樣回傳，不猜。** 這條是實測換來的：`6176`（瑞儀）
    當天在證交所的收盤行情檔裡沒有出現（無成交/暫停交易之類），但它確實是上市股，
    yfinance `6176.TW` 抓得到 59 根 K 棒。若把「名單裡沒有」當成「後綴錯」去翻面，
    就會把一個對的代號改壞。興櫃股、剛掛牌的股同理。
    """
    if not isinstance(code, str) or "." not in code:
        return code
    num, _, suf = code.rpartition(".")
    if suf not in ("TW", "TWO"):
        return code
    official = _LISTING.get(num)
    if official is None or official == suf:
        return code
    return f"{num}.{official}"


def resolve_by_official_name(name: str) -> str | None:
    """拿公司中文全名去官方上市/上櫃名單反查代號；查不到或同名多筆回 None。

    只做**完全比對**（去頭尾空白、剝掉處置股的 `*`）。不做模糊比對——
    「立隆電」vs「資通」、「昇達科」vs「矽瑪」這種錯配，正是模糊猜測會製造的災難。
    """
    if not isinstance(name, str) or not name:
        return None
    return _OFFICIAL_BY_NAME.get(name.replace("*", "").strip())


def _lookup(name: str) -> str | None:
    # 舊版 _ALL.get(name, fallback) 對非字串 hashable 值（例如 Gemini 萬一吐出數字
    # 而不是字串）只會查不到、回傳 fallback，不會拋例外；新版多了 .strip()，
    # 沒有這道防護會對非字串輸入直接 AttributeError——2026-08-01 Codex 審查發現，
    # 索羅門本地修正，確保新寫法至少不比舊寫法更容易炸掉。
    if not isinstance(name, str) or not name:
        return None
    if name in _ALL:
        return _ALL[name]
    stripped = name.strip()
    if stripped in _ALL:
        return _ALL[stripped]
    return _ALL_STRIPPED.get(stripped)


def resolve(name: str, fallback: str = "Unknown") -> str:
    """用公司名稱查代號；查不到回傳 fallback。"""
    return _lookup(name) or fallback


def resolve_code(stock_name: str, current_code: str) -> str:
    """決定一筆訊號最終要寫進 DB 的代號。優先序（2026-08-24 重寫）：

    1. 人工字典 `_TW`/`_US`——最高信任度，但仍過一次後綴校正（字典也可能寫錯尾綴）。
    2. 官方上市/上櫃名單的**公司全名完全比對**——這一層是新加的，用來接住
       「人工字典沒收錄、Gemini 又把代號猜錯家」的情況（實例：語料裡「昇達科」被
       標成 3511.TW，而 3511 是矽瑪；官方名單反查「昇達科」得到 3491.TWO）。
    3. Gemini 給的代號，但**強制過一次上市/上櫃後綴校正**。
    4. 都沒有 → Unknown（`database.save_result()` 會跳過，不寫進 DB）。
    """
    known = _lookup(stock_name)
    if known:
        return normalize_tw_suffix(known)
    official = resolve_by_official_name(stock_name)
    if official:
        return official
    if current_code and current_code != "Unknown":
        return normalize_tw_suffix(current_code)
    return resolve(stock_name, "Unknown")
