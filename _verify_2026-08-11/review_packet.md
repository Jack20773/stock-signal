# 審查素材：stock-signal 第二頁（關注度）與第三頁（逐字稿）

## A. 這個網站是什麼（背景事實）

公開靜態網站 https://jack20773.github.io/stock-signal/ ，追蹤台灣財經 Podcast「股癌」主持人在節目中提到的個股。
流程：逐字稿 → AI（Gemini）萃取「哪一集、哪檔股票、看多(+1)還是看空(-1)、信心等級」→ PostgreSQL → 用真實收盤價計算
「這筆訊號從節目上架日到今天，個股漲跌幅 vs 同期大盤（台股比 0050、美股比 SPY）」→ 產生三個靜態 HTML 頁面。

讀者組成：站主自己、他的朋友、以及從連結點進來、**對這個 Podcast 和這個網站都完全不熟的陌生訪客**。
三頁共用頂部分頁籤：①訊號報告（index.html）②目前關注度（attention.html）③逐字稿（transcripts.html）。

**第一頁的現況（僅供你了解站內一致性，不是這次審查對象）**：主區是「最近訊號」帳本，一筆訊號一張卡，
顯示方向（↑看多／↓看空）、上架日、原話引用、勝負（✓跑贏大盤／✕落後大盤／待觀察）、個股與大盤報酬、該檔歷史勝率帶分母；
次區是收合的「依標的查看履歷」個股排行。第一頁的顏色慣例：勝負用紅（贏）／綠（輸）（台灣股市慣例紅漲綠跌），
方向 chip 刻意改用藍色系表看空，以避免跟勝負色混淆。第一頁另有一段「常駐導讀」（不可關閉），
說明勝率定義、分母、報酬口徑等，理由是可關閉的 onboarding 被關掉後新訪客會只看到裸露數字。

## B. 這次要你審查的兩頁

### B-1. 第二頁「目前關注度」實際渲染文字（真實資料，2026-08-11，共 33 檔）

```text
目前節目關注度
2026-08-11
📊 訊號報告
🔥 目前關注度
📄 逐字稿
💡 怎麼看這個分數
知道了，不用每次都顯示 ✕
這個分數量化「股癌最近反覆在講什麼」，跟這檔過去準不準是兩件事
分數越高代表最近越常被提到、信心等級也越高
「偏多共識／偏空共識」看的是最近多空次數比例
「高度關注但分歧」代表多空次數接近，講者立場不明確，不是無訊號
超過60天沒被提到會自動從這個榜單下架，但歷史紀錄還在主報告
⚠ 反映節目近期討論熱度，不是買賣建議。這個分數只量化「股癌最近反覆在講什麼」， 跟這檔標的過去準不準（歷史勝率）是兩件不同的事——想看歷史勝率請回 主報告，兩者分開看，不要混為一談。
全部
台股
美股
33 / 33 檔
1
台積電
台股
2330.TW
偏多共識（102多／2空）
64.55
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685、EP683、EP681、EP680
「從上禮拜五開始，大家也看到台積電漲停非常誇張，各式各樣的標的都直接從谷底彈上來」— EP685
2
Google
美股
GOOGL
偏多共識（12多／0空）
41.77
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685、EP682、EP681
「Google 前面開財報的時候不是跌嗎？然後跌完之後，很多人就想說因為怎麼樣怎麼樣嘛，結果後來又再漲回去，那請問前面的人是不是就把自己臉打爆了？」— EP685
3
聯發科
台股
2454.TW
偏多共識（19多／1空）
41.39
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685、EP684
「不管是在 MTK 這裡、或者在博通這裡，大家的 Roadmap 都還是一樣，那就算有一些時程上的調整，它應該也不是什麼大不了的事情」— EP685
4
Palantir
美股
PLTR
偏多共識（18多／0空）
40.25
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685、EP682
「我們最近看到 Palantir 直接整個跳上去，我覺得就是一掃過去的陰霾…… Palantir 這個財報數字，當然我覺得已經是沒有意外，它本身就是開一個好的數字，但是重點是什麼？重點是市場願意去反映它」— EP685
5
AMD
美股
AMD
偏多共識（14多／2空）
39.81
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685、EP682、EP681
「只有那個 AMD 開完之後還是疊的，那個蠻神奇的……如果是這樣的話，那就會導致對於這些產品的需求會大量下降，所以他們一定是不希望這種事情發生的」— EP685
6
微軟
美股
MSFT
偏多共識（5多／2空）
26.92
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685
「微軟算是一個分界點，所以微軟的這份財報，他開完之後他上去，其實在我們的判讀裡面，他也是一個非常重要的指標」— EP685
7
Cloudflare
美股
NET
偏多共識（17多／0空）
23.21
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685
「有些像是資安，過去一直被誤會的，其實很多都跑去新高、都是持續地越漲越多……或者像像是 Palantir、或是像 Cloudflare，之前也有一個論述是講說他們也都會被擊敗……後來發現說沒有辦法」— EP685
8
台達電
台股
2308.TW
偏多共識（9多／0空）
18.78
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685
「像最近台達電、或是光寶出來講，基本上他們的說法，你就不會去質疑說 800V 這個東西不會出現，它就只是可能現在中繼先用 400V」— EP685
9
Tesla
美股
TSLA
偏多共識（43多／5空）
17.57
關注度
最後提及 2026-07-25（EP682）
近30天提及：EP682、EP680
「Tesla 也是花很多錢，但是 Tesla 花的錢，它的賽道就跟大家有點不太一樣，它是在拚 Physical AI 這一塊了，所以會相對地難評價一點。」— EP682
10
力積電
台股
6770.TW
偏多共識（3多／0空）
17.53
關注度
最後提及 2026-08-01（EP684）
近30天提及：EP684、EP679
「黃崇仁對我的影響就是，他的力積電、愛普我都是賺錢的。... 那個力積電早日破百，對，希望這個——也不要只有說力積電，就所有這一波遭受到重擊的股票，希望大家都可以盡快早日回到前高」— EP684
11
博通
美股
AVGO
偏多共識（16多／3空）
16.72
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685
「不管是在 MTK 這裡、或者在博通這裡，大家的 Roadmap 都還是一樣，那就算有一些時程上的調整，它應該也不是什麼大不了的事情」— EP685
12
光寶科
台股
2301.TW
偏多共識（2多／0空）
16.21
關注度
最後提及 2026-08-05（EP685）
近30天提及：EP685
「像最近台達電、或是光寶出來講，基本上他們的說法，你就不會去質疑說 800V 這個東西不會出現」— EP685
13
德州儀器
美股
TXN
偏多共識（2多／0空）
13.06
關注度
最後提及 2026-07-25（EP682）
近30天提及：EP682
「Texas Instrument，就是德州儀器 TXN 或是 TI... 它在這次的電話會，基本上釋出一個超級好的訊號，就是告訴大家說它就是看到一個全面性的復甦，東西都上來，車用中心的表現很好，他們開始漲價。」— EP682
14
愛普*
台股
6531.TW
偏多共識（4多／0空）
12.84
關注度
最後提及 2026-08-01（EP684）
近30天提及：EP684
「黃崇仁對我的影響就是，他的力積電、愛普我都是賺錢的。... 所以黃崇仁的股票呢，就是氣氛對了上去就會賺錢，所以有時候會洗比較久，像那時候愛普就洗了好久好久。」— EP684
15
NVIDIA
美股
NVDA
偏多共識（49多／2空）
9.37
關注度
最後提及 2026-07-11（EP678）
近30天提及：無
「NVIDIA 的話是直接再次的攻到 200 美元大關了，就很久沒有看到 NVIDIA 連續出這種紅 K，然後重新的爬上季線，這個長得還蠻好看的」— EP678
16
國巨
台股
2327.TW
偏多共識（14多／2空）
7.82
關注度
最後提及 2026-07-08（EP677）
近30天提及：無
「過去一個比較大、可以塞很多錢的族群是被動元件，像國巨、華新科這種最大的，法人是有辦法parking進去的...只是按照自己的經驗，一般來講如果拉回到這樣一個程度，會需要橫盤去做整理。」— EP677
17
Intel
美股
INTC
偏多共識（8多／2空）
7.16
關注度
最後提及 2026-07-22（EP681）
近30天提及：EP681
「Intel 當然它也是有端出新東西啊，只是呢，它的 Oak Stream... 那應該是要等到今年年底或明年年初才會出來，所以 AMD 又可以搶先一點」— EP681
18
SpaceX
美股
SPCX
偏多共識（2多／0空）
7.14
關注度
最後提及 2026-07-18（EP680）
近30天提及：EP680
「那這禮拜看到 SpaceX 的股價又繼續落地，但我還是非常勇敢的在持續去加，後來就真的越來越喜歡這家公司。...那就是跟可能在裡面工作的一些朋友聊天完之後，就會覺得應該要再買更多。」— EP680
19
Meta
美股
META
偏多共識（4多／0空）
5.07
關注度
最後提及 2026-07-11（EP678）
近30天提及：無
「祖克柏的訪問裡面，好像是昨天還前天他出來證實了，就是我們這邊的意見才是對的，就是他並沒有要退出，他甚至是要滿倉殺進去，然後更加用力的做多。」— EP678
20
CrowdStrike
美股
CRWD
偏多共識（8多／0空）
4.53
關注度
最後提及 2026-07-08（EP677）
近30天提及：無
「那時候當然也可能是因為我自己手上有CrowdStrike，所以可能也有一點愛屋及烏吧... 你去回測就會知道，真的很多時候大家覺得市場一定是對的，市場才不是一定是對的... 這些資安全部都在右上角。」— EP677
21
Marvell
美股
MRVL
偏多共識（16多／3空）
2.42
關注度
最後提及 2026-06-27（EP674）
近30天提及：無
「Marvell 也是有壓到。但是最近這幾檔都稍微有去做一點調節。」— EP674
22
ADI
美股
ADI
偏多共識（1多／0空）
2.2
關注度
最後提及 2026-07-11（EP678）
近30天提及：無
「我們已經注意到像 ADI，就是一個全球非常大的一個類比 IC 的廠商，他們也是發出了漲價信，其實我們也是注意到說，在功率元件這邊有一個全面漲價的一個狀態」— EP678
23
華新科
台股
2492.TW
偏多共識（2多／0空）
1.99
關注度
最後提及 2026-07-08（EP677）
近30天提及：無
「過去一個比較大、可以塞很多錢的族群是被動元件，像國巨、華新科這種最大的，法人是有辦法parking進去的...」— EP677
24
Apple
美股
A
```

### B-2. 第三頁「逐字稿」實際渲染文字（真實資料，2026-08-11，共 685 集）

```text
逐字稿
2026-08-11 · 純瀏覽用，不是訊號查核工具
📊 訊號報告
🔥 目前關注度
📄 逐字稿
💡 這頁在做什麼
知道了，不用每次都顯示 ✕
這裡是逐字稿原文，純瀏覽用，不是訊號查核工具
點集數標題可以展開／收合看全文
搜尋框可以全文檢索關鍵字，第一次搜尋要下載全部逐字稿，請稍候
部分較舊集數逐字稿檔案可能缺失，會顯示明確提示，不是網頁壞了
共 685 集
EP685
奧德賽觀影與幸福無聊論
2026-08-05
▸
EP684
五歲家書與降槓桿浩劫
2026-08-01
▸
EP683
DUV鬼故事與黃金葛玄學
2026-07-29
▸
EP682
紅眼路比與魂系股災
2026-07-25
▸
EP681
人道走廊與沙沙西瓜
2026-07-22
▸
EP680
筷子信仰與台積電心碎記
2026-07-18
▸
EP679
紅酒燒幣記與韓客斷頭劫
2026-07-15
▸
EP678
觀音功利許願論與光通窄寬之辯
2026-07-11
▸
EP677
四代同堂槓桿論與研報獵巫記
2026-07-08
▸
EP676
凱杜飯店遛娃記與祖克柏癡漢論
2026-07-04
▸
EP675
蕭南資本造夢記與動能追高論
2026-07-01
▸
EP674
上半年高光總結與蘋果漲價論
2026-06-27
▸
EP673
全聯淘酒記與電阻漲浪論
2026-06-24
▸
EP672
功率元件缺貨論與軟體職涯重整
2026-06-20
▸
EP671
離散元件覓蹤與隨機人生論
```

## C. 原始碼切片（原檔逐行複製，含行號，未做任何刪改）

### C-1. `attention.py` 全檔（分數計算）

```python
1: """
2: 「目前節目關注度／方向共識」評分模組（2026-08-02 索羅門新增，任務檔第8節）。
3: 
4: 完整背景、Codex 原始分析、定案參數見
5: 100_Todo/projects/2026-08-02_stock-signal報告第二頁-關注度排序計畫.md
6: （讀該檔「定案補充」段落——4個參數 h/h_g/k/60天下架門檻已由使用者拍板，
7: 不是索羅門自己調校出來的，這裡直接套用，不做任何反向優化）。
8: 
9: 核心判斷：這個分數量化「節目近期反覆在談什麼」（討論熱度），不是「建議
10: 強度」——不能直接證明現在值得買賣，使用介面必須明確標示這個定位差異
11: （見 report_html.py::generate_html_attention() 的首屏警語）。
12: """
13: import json
14: import logging
15: import math
16: import re
17: from datetime import date
18: from pathlib import Path
19: 
20: # ── 已拍板定案參數（使用者2026-08-01深夜裁決，h/h_g/60天門檻不可反向優化調整）
21: H = 21           # 一般衰減半衰期（天）
22: H_G = 14         # 最後提及防呆項半衰期（天）
23: DELIST_DAYS = 60  # 下架門檻：超過這麼多天沒被提到，不列入「目前關注」榜單
24: 
25: # K：飽和常數——2026-08-02 索羅門「重大自主決策」，見 SOLOMON_HANDOFF.md /
26: # 完工報告的 autonomous_decisions 詳細記錄，這裡只留精簡結論：
27: #
28: # 原拍板值 K=5 是用「近90天內同標的未衰減原始提及次數」反推的（查到台積電
29: # 12次、代入 100×(1-e^(-count/5)) 得91%飽和，覺得曲線合理），但正式公式
30: # 實際餵給 K 的是 A（時間衰減後的加權和），量綱跟校準時的「未衰減次數」
31: # 不一致——純數學可證：即使每集都提、永遠持續、每次都最高信心的理論上限
32: # 情境，週更間隔下 A 穩態上限僅約4.85，套 K=5 只能到62%飽和，10天間隔約
33: # 51%、14天間隔約42%，連校準設想的91%都到不了。套用真實DB資料（935筆
34: # 訊號/680集），全部標的分數集中在1~7分（滿分100），連討論度最高的台積電
35: # （97次看多）都只有6.52分——命中任務檔8d.4自訂的「參數明顯不合理」觸發
36: # 條件。經 Codex challenge-mode 覆核（session 019fbe0b，read-only，2026-08-02）
37: # 確認判斷成立，建議 K 落在1-2量級（同樣三個時間參數h/h_g/60天不動）。索羅門
38: # 最終選擇 K=2（Codex建議區間上緣，取整數方便解釋）：驗證後「每週穩定被高
39: # 信心提及、且今天剛被提到」的標的可達約99%飽和（K=1時）、K=2時約91%
40: # （對照原始12次校準的目標曲線），比K=5的62%上限更貼近校準原意，同時不像
41: # K=1那樣過度靈敏（單次提及就衝很高分）。這次真實資料抓到的分數仍普遍偏低
42: # （最高約12分）是另一個獨立因素：資料庫最新分析集數的實際上架日距抓取當下
43: # 已有約15-30+天空窗（沒有更近期的已分析集數），h_g=14天防呆項本來就設計成
44: # 懲罰這種「好一陣子沒提」的情況——這部分是h_g參數原本設計的正常行為，不是
45: # K失配的一部分，索羅門沒有連帶調整h_g。
46: K = 2
47: 
48: # confidence_level → q_i 權重映射：任務檔/計畫檔只定義「q_i = confidence_level
49: # 映射權重」，沒有給具體數值——這是索羅門的判斷（一般分岔點，非任務檔已拍板
50: # 的4個參數之一）。DB 實際只出現 High/Medium/Low 三種值（2026-08-01 索羅門
51: # 查證），採用線性遞減：High=1.0（超級看好/超級看壞，語意=講者投資信念強度，
52: # 見計畫檔定案補充第1點）、Medium=0.6、Low=0.3。未知/缺值時保守給 Medium
53: # 同等權重，不當作 0（避免資料品質問題讓某檔標的整批訊號憑空消失）。
54: _CONF_WEIGHT = {"High": 1.0, "Medium": 0.6, "Low": 0.3}
55: _DEFAULT_WEIGHT = 0.6
56: 
57: # 共識分歧顯示門檻：|consensus| 小於這個值且多空皆有 → 顯示「高度關注但分歧」，
58: # 不是「無訊號」（任務檔8b明確要求，數值本身是索羅門判斷，非拍板參數）。
59: _DIVERGENCE_THRESHOLD = 0.15
60: 
61: _EPISODES_PATH = Path(__file__).parent / "episodes.json"
62: _ep_date_cache: dict[str, str] | None = None
63: 
64: 
65: def _load_episode_dates() -> dict[str, str]:
66:     """沿用 performance.py::_load_episodes() 的模式：讀本地 episodes.json，
67:     episode_id (EPxxx) -> 上架日 (YYYY-MM-DD)。不用 signals.analysis_date
68:     （已查證是AI處理當天，不是真實上架日，見計畫檔定案補充第2點）——這條規則
69:     是任務檔明確拍板的核心設計，讀取失敗時**不能悄悄退回 analysis_date**，
70:     寧可讓呼叫端拿不到日期而跳過該筆訊號（見 compute_attention() 的
71:     ep_date is None 分支），也不要用錯誤時間基準算出一個看起來正常、實際
72:     不可信的分數（2026-08-02 完工前 Codex 覆核抓到：原本的 fallback 設計會
73:     讓這條核心規則在 episodes.json 讀取失敗或某集查無資料時被悄悄違反且無
74:     警告，這裡修正）。"""
75:     global _ep_date_cache
76:     if _ep_date_cache is not None:
77:         return _ep_date_cache
78:     _ep_date_cache = {}
79:     if not _EPISODES_PATH.exists():
80:         logging.warning(
81:             f"[attention] 找不到 {_EPISODES_PATH}，所有訊號都無法計算真實上架日，"
82:             f"這次「目前關注度」榜單會是空的（不會用 analysis_date 頂替）"
83:         )
84:         return _ep_date_cache
85:     try:
86:         data = json.loads(_EPISODES_PATH.read_text(encoding="utf-8"))
87:         _ep_date_cache = {
88:             f"EP{e['number']}": e["date"]
89:             for e in data if e.get("date") and e.get("number")
90:         }
91:     except Exception as ex:
92:         logging.warning(
93:             f"[attention] episodes.json 讀取/解析失敗，所有訊號都無法計算真實上架日："
94:             f"{ex}（不會用 analysis_date 頂替）"
95:         )
96:     return _ep_date_cache
97: 
98: 
99: def _ep_num(ep: str) -> int:
100:     """沿用 report_html.py::_ep_num() 同一套 regex，任務檔8a明確要求不重新發明。"""
101:     m = re.search(r"\d+", ep or "")
102:     return int(m.group()) if m else 0
103: 
104: 
105: def _episode_date(episode_id: str) -> str | None:
106:     """回傳 episode_id 對應的真實上架日；episodes.json 裡找不到就回傳 None
107:     ——**不 fallback 到 analysis_date**，那是任務檔明確禁止的時間基準（見
108:     上方 _load_episode_dates() 說明）。呼叫端（compute_attention()）據此
109:     跳過這筆訊號，不用錯誤日期硬湊出一個分數。已知代價：極少數 episode_id
110:     在 episodes.json 查無資料時（本輪查證是680集裡有679集有完整date+number，
111:     覆蓋率高但非100%），那幾筆訊號會被排除在關注度計算外，不會讓整檔標的
112:     消失（除非該標的全部訊號都剛好卡在這極少數集數）。"""
113:     return _load_episode_dates().get(episode_id)
114: 
115: 
116: def _conf_weight(level) -> float:
117:     return _CONF_WEIGHT.get(level, _DEFAULT_WEIGHT)
118: 
119: 
120: def _sat(x: float) -> float:
121:     """飽和函數 100×(1-e^(-x/k))，Attention 與 U_bull/U_bear 共用同一個形狀
122:     （計畫檔定案補充：「U_bull/U_bear 用同樣的加權飽和邏輯分別算」）。"""
123:     return 100 * (1 - math.exp(-x / K))
124: 
125: 
126: def compute_attention(signals: list[dict], today: date | None = None) -> list[dict]:
127:     """signals：database.list_signals() 或等效 dict list，需含 episode_id/
128:     stock_code/stock_name/action/confidence_level/analysis_date/raw_reason/
129:     exact_quote 欄位。回傳依 Attention 分數降冪排列的標的清單，已依60天
130:     下架規則排除 age_last > 60 的標的（歷史頁另外查，這次不做）。"""
131:     today = today or date.today()
132: 
133:     # 去重規則（計畫檔定案）：(episode_number, stock_code, action) 三元組，
134:     # 同集同標的同方向只算一次，避免同集重述虛增次數。
135:     dedup: dict[tuple, dict] = {}
136:     for s in signals:
137:         code = s.get("stock_code")
138:         if not code or code == "Unknown":
139:             continue
140:         ep_id  = s.get("episode_id") or ""
141:         ep_num = _ep_num(ep_id)
142:         action = s.get("action", "0")
143:         key = (ep_num, code, action)
144:         if key in dedup:
145:             continue
146: 
147:         ep_date_str = _episode_date(ep_id)
148:         try:
149:             ep_date = date.fromisoformat(ep_date_str) if ep_date_str else None
150:         except ValueError:
151:             ep_date = None
152:         if ep_date is None:
153:             continue  # 沒有可用日期就無法算 age，不用猜測值硬湊
154: 
155:         age = (today - ep_date).days
156:         if age < 0:
157:             age = 0  # 保險絲：理論上不會有未來日期，防禦負值讓衰減公式爆炸（>1)
158: 
159:         dedup[key] = {**s, "_ep_num": ep_num, "_ep_date": ep_date_str, "_age": age}
160: 
161:     by_code: dict[str, list[dict]] = {}
162:     for item in dedup.values():
163:         by_code.setdefault(item["stock_code"], []).append(item)
164: 
165:     results = []
166:     for code, items in by_code.items():
167:         name = next((i.get("stock_name") for i in items if i.get("stock_name")), code)
168: 
169:         weighted = [(_conf_weight(i.get("confidence_level")) * (2 ** (-i["_age"] / H)), i)
170:                     for i in items]
171:         A = sum(w for w, _ in weighted)
172: 
173:         bull_w = sum(w for w, i in weighted if i.get("action") == "+1")
174:         bear_w = sum(w for w, i in weighted if i.get("action") == "-1")
175:         U_bull = _sat(bull_w)
176:         U_bear = _sat(bear_w)
177:         consensus = (U_bull - U_bear) / (U_bull + U_bear) if (U_bull + U_bear) > 0 else None
178: 
179:         last_item = min(items, key=lambda i: i["_age"])
180:         age_last  = last_item["_age"]
181: 
182:         if age_last > DELIST_DAYS:
183:             continue  # 60天下架規則：只影響是否列入「目前關注」榜單，不刪除資料
184: 
185:         attention = _sat(A) * (2 ** (-age_last / H_G))
186: 
187:         recent_30_eps = sorted({i["_ep_num"] for i in items if i["_age"] <= 30}, reverse=True)
188: 
189:         quote_item = max(
190:             (i for i in items if (i.get("exact_quote") or "").strip()),
191:             key=lambda i: i["_ep_num"], default=None,
192:         )
193: 
194:         bull_n = sum(1 for i in items if i.get("action") == "+1")
195:         bear_n = sum(1 for i in items if i.get("action") == "-1")
196: 
197:         results.append({
198:             "code": code,
199:             "name": name,
200:             "mkt": "tw" if (code.endswith(".TW") or code.endswith(".TWO")) else "us",
201:             "attention": round(attention, 2),
202:             "consensus": round(consensus, 3) if consensus is not None else None,
203:             "bull_n": bull_n,
204:             "bear_n": bear_n,
205:             "neutral_n": sum(1 for i in items if i.get("action") == "0"),
206:             "total_mentions": len(items),
207:             "age_last": age_last,
208:             "last_episode": last_item.get("episode_id", ""),
209:             "last_date": last_item["_ep_date"],
210:             "recent_30d_eps": [f"EP{n}" for n in recent_30_eps],
211:             "quote": (quote_item.get("exact_quote") or "").strip() if quote_item else "",
212:             "quote_ep": quote_item.get("episode_id", "") if quote_item else "",
213:             "raw_reason": (last_item.get("raw_reason") or "").strip(),
214:             "is_divergent": bull_n > 0 and bear_n > 0
215:                              and consensus is not None and abs(consensus) < _DIVERGENCE_THRESHOLD,
216:         })
217: 
218:     results.sort(key=lambda r: r["attention"], reverse=True)
219:     return results
220: 
221: 
222: def consensus_label(row: dict) -> tuple[str, str]:
223:     """回傳 (顯示文字, 顏色)。5次看多5次看空這種情況要老實標成「高度關注但
224:     分歧」，不能顯示成「無訊號」（任務檔8b明確要求）。"""
225:     bull_n, bear_n, consensus = row["bull_n"], row["bear_n"], row["consensus"]
226:     if bull_n == 0 and bear_n == 0:
227:         return ("中性／無方向", "#999")
228:     if row["is_divergent"]:
229:         return (f"高度關注但分歧（{bull_n}次看多／{bear_n}次看空）", "#c77c1f")
230:     if consensus is not None and consensus > 0:
231:         return (f"偏多共識（{bull_n}多／{bear_n}空）", "#d9534f")
232:     return (f"偏空共識（{bull_n}多／{bear_n}空）", "#2b8a3e")
```

### C-2. `report_html.py::generate_html_attention()`（第二頁渲染）

```python
1570: def generate_html_attention(rows: list[dict], title: str = "目前節目關注度") -> str:
1571:     """rows：attention.compute_attention() 的回傳值（已依 Attention 降冪排列、
1572:     已排除60天下架的標的）。文字欄位一律套用 _esc()（比照1a的escapeHtml防護
1573:     要求，這裡是純 Python 端渲染所以用 html.escape 版本的 _esc()，跟
1574:     generate_html_email() 同一套防護）。"""
1575:     today = date.today().isoformat()
1576: 
1577:     def _card(rank: int, r: dict) -> str:
1578:         label, color = attention.consensus_label(r)
1579:         name      = _esc(r["name"])
1580:         code      = _esc(r["code"])
1581:         mkt_label = "台股" if r["mkt"] == "tw" else "美股"
1582:         last_ep   = _esc(r["last_episode"])
1583:         recent_eps = "、".join(_esc(e) for e in r["recent_30d_eps"][:8]) or "無"
1584: 
1585:         quote_html = ""
1586:         if r["quote"]:
1587:             quote_html = (
1588:                 f'<div style="margin-top:6px;padding-left:10px;border-left:3px solid #ccc;'
1589:                 f'color:#888;font-style:italic;font-size:13px;">「{_esc(r["quote"])}」'
1590:                 f'<span style="color:#bbb;font-size:11px;margin-left:6px;">— {_esc(r["quote_ep"])}</span></div>'
1591:             )
1592: 
1593:         return f'''
1594:         <div class="att-card" data-name="{(name + code).lower()}" data-mkt="{r["mkt"]}">
1595:           <div style="display:flex;align-items:center;gap:10px;">
1596:             <div style="font-size:20px;font-weight:800;color:#bbb;min-width:28px;text-align:right;">{rank}</div>
1597:             <div style="flex:1;min-width:0;">
1598:               <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
1599:                 <span style="font-size:16px;font-weight:bold;color:#1a252f;">{name}</span>
1600:                 <span style="font-size:10px;background:#f1f3f5;color:#888;border-radius:4px;padding:1px 6px;">{mkt_label}</span>
1601:                 <span style="font-size:12px;color:#aaa;">{code}</span>
1602:               </div>
1603:               <div style="font-size:12px;margin-top:3px;color:{color};font-weight:bold;">{label}</div>
1604:             </div>
1605:             <div style="text-align:right;">
1606:               <div style="font-size:24px;font-weight:800;color:#2b6cb0;">{r["attention"]}</div>
1607:               <div style="font-size:10px;color:#bbb;">關注度</div>
1608:             </div>
1609:           </div>
1610:           <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:11px;color:#999;flex-wrap:wrap;gap:4px;">
1611:             <span>最後提及 {r["last_date"]}（{last_ep}）</span>
1612:             <span>近30天提及：{recent_eps}</span>
1613:           </div>
1614:           {quote_html}
1615:         </div>'''
1616: 
1617:     cards_html = "".join(_card(i + 1, r) for i, r in enumerate(rows))
1618: 
1619:     return f"""<!DOCTYPE html>
1620: <html>
1621: <head>
1622: <meta charset="utf-8">
1623: <meta name="viewport" content="width=device-width,initial-scale=1">
1624: <title>{_esc(title)}</title>
1625: <style>
1626:   body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
1627:   .wrap{{max-width:760px;margin:20px auto;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.07);overflow:hidden;}}
1628:   @media(max-width:600px){{.wrap{{margin:0;border-radius:0;}}}}
1629:   .att-card{{border:1px solid #eee;border-radius:8px;padding:14px 16px;margin:0 16px 10px;background:#fff;}}
1630:   .att-card.hidden{{display:none;}}
1631:   .filter-btn{{margin:2px 3px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:13px;}}
1632:   .btn-active{{background:#1a252f!important;color:#fff!important;border-color:#1a252f!important;}}
1633: {_NAV_TABS_CSS}
1634: {_ONBOARD_CSS}
1635: </style>
1636: </head>
1637: <body>
1638: <div class="wrap">
1639:   <div style="background:#1a252f;padding:20px;text-align:center;color:#fff;border-radius:8px 8px 0 0;">
1640:     <div style="font-size:20px;font-weight:bold;">{_esc(title)}</div>
1641:     <div style="color:#b3c1cd;font-size:13px;margin-top:4px;">{today}</div>
1642:   </div>
1643:   {_render_nav_tabs('attention')}
1644:   {_render_onboarding('sig_onboard_dismissed_attention', '怎麼看這個分數', [
1645:       "這個分數量化「股癌最近反覆在講什麼」，跟這檔過去準不準是兩件事",
1646:       "分數越高代表最近越常被提到、信心等級也越高",
1647:       "「偏多共識／偏空共識」看的是最近多空次數比例",
1648:       "「高度關注但分歧」代表多空次數接近，講者立場不明確，不是無訊號",
1649:       "超過60天沒被提到會自動從這個榜單下架，但歷史紀錄還在主報告",
1650:   ])}
1651: 
1652:   <!-- 首屏警語（任務檔8b明確要求，定位差異必須在介面上明確標示） -->
1653:   <div style="margin:16px;padding:12px 16px;background:#fff8e1;border:1px solid #ffe082;border-radius:8px;font-size:13px;color:#8a6d1f;line-height:1.6;">
1654:     ⚠ 反映節目近期討論熱度，不是買賣建議。這個分數只量化「股癌最近反覆在講什麼」，
1655:     跟這檔標的過去準不準（歷史勝率）是兩件不同的事——想看歷史勝率請回
1656:     <a href="index.html" style="color:#8a6d1f;">主報告</a>，兩者分開看，不要混為一談。
1657:   </div>
1658: 
1659:   <div style="padding:0 16px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
1660:     <input id="att-search" type="text" placeholder="搜尋標的名稱、代號..."
1661:       oninput="attFilter()"
1662:       style="flex:1;max-width:240px;padding:6px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
1663:     <button id="amkt-all" class="filter-btn btn-active" onclick="attSetMkt('all')">全部</button>
1664:     <button id="amkt-tw"  class="filter-btn" onclick="attSetMkt('tw')">台股</button>
1665:     <button id="amkt-us"  class="filter-btn" onclick="attSetMkt('us')">美股</button>
1666:     <span id="att-count" style="font-size:12px;color:#bbb;margin-left:auto;"></span>
1667:   </div>
1668: 
1669:   <div id="att-list">{cards_html}</div>
1670:   <div id="att-empty" style="display:none;padding:30px;text-align:center;color:#888;font-size:13px;">沒有符合篩選條件的標的</div>
1671: 
1672:   <div style="padding:14px;text-align:center;font-size:11px;color:#bbb;border-top:1px solid #f0f0f0;">
1673:     共 {len(rows)} 檔標的目前列入關注（超過 {attention.DELIST_DAYS} 天沒被提到自動下架，只留歷史頁）· 僅供參考，非投資建議
1674:   </div>
1675: </div>
1676: <script>
1677: {_onboard_js('sig_onboard_dismissed_attention')}
1678: let _amkt = 'all';
1679: function attSetMkt(m) {{
1680:   _amkt = m;
1681:   document.querySelectorAll('.filter-btn').forEach(b => {{
1682:     if (b.id.startsWith('amkt-')) b.classList.toggle('btn-active', b.id === 'amkt-' + m);
1683:   }});
1684:   attFilter();
1685: }}
1686: function attFilter() {{
1687:   const q = document.getElementById('att-search').value.trim().toLowerCase();
1688:   const cards = document.querySelectorAll('.att-card');
1689:   let visible = 0;
1690:   cards.forEach(c => {{
1691:     const nameOk = !q || (c.dataset.name || '').includes(q);
1692:     const mktOk  = _amkt === 'all' || c.dataset.mkt === _amkt;
1693:     const ok = nameOk && mktOk;
1694:     c.classList.toggle('hidden', !ok);
1695:     if (ok) visible++;
1696:   }});
1697:   document.getElementById('att-count').textContent = visible + ' / ' + cards.length + ' 檔';
1698:   document.getElementById('att-empty').style.display = visible === 0 ? '' : 'none';
1699: }}
1700: document.addEventListener('DOMContentLoaded', attFilter);
1701: </script>
1702: </body>
1703: </html>"""
1704: 
1705: 
1706: # ── 逐字稿詳細頁（2026-08-02 索羅門新增，任務1d）───────────────────────────
1707: # 目標：純瀏覽方便，不是訊號查核工具（不用對應到某筆訊號跳轉）。
1708: #
1709: # 679份逐字稿（episodes.json列680集，但transcripts/目錄實測只有679份.md檔，
1710: # EP677缺檔——這是既有資料缺口，不是本工具的bug，見crosscheck.py同一輪的
1711: # 發現與下方 export_transcripts_data() 的處理）共約35MB，遠超過任務檔提示的
1712: # 5MB量級門檻，不可能全部塞進單一HTML的JSON blob。設計：
1713: #   - 頁面只內嵌集數清單的中繼資料（集數/標題/日期），JSON payload維持KB等級。
1714: #   - 每集預設收合，首次展開才用 fetch('transcripts_data/EP<n>.txt') 動態抓
1715: #     該集全文（transcripts_data/ 由 export_transcripts_data() 從
1716: #     transcripts/*.md 複製成純文字檔，部署時原樣複製進 _site/）。
1717: #   - 全文搜尋：輸入關鍵字時才並行 fetch 全部集數全文做一次性搜尋（使用者
1718: #     主動觸發才付出這個網路成本，不影響首屏載入），抓過的集數會快取，
1719: #     不會同一集重複下載。
1720: #   - 逐字稿內容一律用 textContent 賦值渲染（瀏覽器自動跳脫，等同於
1721: #     escapeHtml() 的防護效果，比手動escape更不容易漏放）。
1722: 
1723: TRANSCRIPTS_DIR_NAME = "transcripts"
1724: TRANSCRIPTS_DATA_DIR_NAME = "transcripts_data"
1725: 
1726: 
```

### C-3. `report_html.py::export_transcripts_data()` 與 `generate_html_transcripts()`（第三頁）

```python
1727: def export_transcripts_data(transcripts_dir: str = TRANSCRIPTS_DIR_NAME,
1728:                              out_dir: str = TRANSCRIPTS_DATA_DIR_NAME) -> int:
1729:     """把 transcripts/EP<n>_標題.md 逐一複製成 out_dir/EP<n>.txt（純文字，
1730:     檔名正規化成不含中文/空白，前端 JS 用集數直接組 fetch 路徑，不用處理
1731:     URL encoding）。只在來源檔比目的檔新，或目的檔不存在時才複製，避免
1732:     每次跑報告都重複寫入679個檔案。回傳實際複製的檔案數。"""
1733:     os.makedirs(out_dir, exist_ok=True)
1734:     copied = 0
1735:     for fname in os.listdir(transcripts_dir):
1736:         m = re.match(r"EP(\d+)_", fname)
1737:         if not m:
1738:             continue
1739:         src = os.path.join(transcripts_dir, fname)
1740:         dst = os.path.join(out_dir, f"EP{m.group(1)}.txt")
1741:         if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
1742:             shutil.copyfile(src, dst)
1743:             copied += 1
1744:     return copied
1745: 
1746: 
1747: def generate_html_transcripts(episodes: list[dict], title: str = "逐字稿") -> str:
1748:     """episodes：episodes.json 內容（number/title/display_title/date...）。
1749:     只用來組『集數清單』中繼資料，不讀逐字稿內容本身（內容由前端 lazy fetch）。
1750:     找不到對應 transcripts_data/EP<n>.txt 的集數（目前已知 EP677）一樣列出來，
1751:     展開時 fetch 404 會顯示清楚的「這集逐字稿檔案缺失」提示，不是靜默失敗。"""
1752:     today = date.today().isoformat()
1753:     eps_sorted = sorted(episodes, key=lambda e: e.get("number", 0), reverse=True)
1754:     meta = []
1755:     for e in eps_sorted:
1756:         # 2026-08-02完工前Codex最終審查指出：number未經型別驗證就直接插進
1757:         # HTML屬性與inline onclick JS（見下方_item()），episodes.json是從
1758:         # 外部網站下載的資料，理論上若上游被污染塞進非整數字串，這裡會變成
1759:         # 一個stored XSS缺口。用int()強制轉型當防線——轉不成功代表資料本身
1760:         # 有問題，跳過這筆並警告，不要讓非整數值有機會流進HTML/JS。
1761:         try:
1762:             num = int(e.get("number"))
1763:         except (TypeError, ValueError):
1764:             logging.warning(f"[report_html] episodes.json 有一筆 number 不是合法整數，跳過：{e.get('number')!r}")
1765:             continue
1766:         meta.append({
1767:             "num":   num,
1768:             "title": e.get("display_title") or e.get("title") or "",
1769:             "date":  e.get("date", ""),
1770:         })
1771:     meta_json = _json_for_script(meta, ensure_ascii=False)
1772: 
1773:     def _item(m: dict) -> str:
1774:         num = m["num"]
1775:         return f'''
1776:         <div class="tr-item" data-num="{num}" data-title="{_esc(m["title"]).lower()}">
1777:           <div class="tr-head" onclick="trToggle({num})">
1778:             <span class="tr-num">EP{num}</span>
1779:             <span class="tr-title">{_esc(m["title"])}</span>
1780:             <span class="tr-date">{_esc(m["date"])}</span>
1781:             <span class="tr-arrow" id="tr-arrow-{num}">&#9656;</span>
1782:           </div>
1783:           <div class="tr-body" id="tr-body-{num}" style="display:none;"></div>
1784:         </div>'''
1785: 
1786:     items_html = "".join(_item(m) for m in meta)
1787: 
1788:     return f"""<!DOCTYPE html>
1789: <html>
1790: <head>
1791: <meta charset="utf-8">
1792: <meta name="viewport" content="width=device-width,initial-scale=1">
1793: <title>{_esc(title)}</title>
1794: <style>
1795:   body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
1796:   .wrap{{max-width:820px;margin:20px auto;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.07);overflow:hidden;}}
1797:   @media(max-width:600px){{.wrap{{margin:0;border-radius:0;}}}}
1798:   .tr-item{{border-bottom:1px solid #eee;}}
1799:   .tr-head{{display:flex;align-items:center;gap:8px;padding:10px 16px;cursor:pointer;flex-wrap:wrap;}}
1800:   .tr-head:hover{{background:#fafbfc;}}
1801:   .tr-num{{font-size:12px;color:#fff;background:#2b6cb0;border-radius:4px;padding:2px 6px;font-weight:bold;white-space:nowrap;}}
1802:   .tr-title{{font-size:14px;color:#1a252f;flex:1;min-width:120px;}}
1803:   .tr-date{{font-size:11px;color:#aaa;white-space:nowrap;}}
1804:   .tr-arrow{{color:#bbb;font-size:12px;}}
1805:   .tr-body{{padding:4px 16px 16px;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.7;color:#444;background:#fafcff;}}
1806:   .tr-item.hidden{{display:none;}}
1807: {_NAV_TABS_CSS}
1808: {_ONBOARD_CSS}
1809: </style>
1810: </head>
1811: <body>
1812: <div class="wrap">
1813:   <div style="background:#1a252f;padding:20px;text-align:center;color:#fff;border-radius:8px 8px 0 0;">
1814:     <div style="font-size:20px;font-weight:bold;">{_esc(title)}</div>
1815:     <div style="color:#b3c1cd;font-size:13px;margin-top:4px;">{today} · 純瀏覽用，不是訊號查核工具</div>
1816:   </div>
1817:   {_render_nav_tabs('transcripts')}
1818:   {_render_onboarding('sig_onboard_dismissed_transcripts', '這頁在做什麼', [
1819:       "這裡是逐字稿原文，純瀏覽用，不是訊號查核工具",
1820:       "點集數標題可以展開／收合看全文",
1821:       "搜尋框可以全文檢索關鍵字，第一次搜尋要下載全部逐字稿，請稍候",
1822:       "部分較舊集數逐字稿檔案可能缺失，會顯示明確提示，不是網頁壞了",
1823:   ])}
1824: 
1825:   <div style="padding:0 16px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px;">
1826:     <input id="tr-search" type="text" placeholder="全文搜尋（首次搜尋需下載全部逐字稿，請稍候）..."
1827:       oninput="trOnSearchInput(this.value)"
1828:       style="flex:1;max-width:320px;padding:6px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
1829:     <span id="tr-status" style="font-size:12px;color:#bbb;">共 {len(meta)} 集</span>
1830:   </div>
1831: 
1832:   <div id="tr-list">{items_html}</div>
1833:   <div id="tr-empty" style="display:none;padding:30px;text-align:center;color:#888;font-size:13px;">沒有符合搜尋條件的集數</div>
1834: 
1835:   <div style="padding:14px;text-align:center;font-size:11px;color:#bbb;border-top:1px solid #f0f0f0;">
1836:     共 {len(meta)} 集逐字稿 · 純瀏覽用，不代表節目立場
1837:   </div>
1838: </div>
1839: <script>
1840: {_onboard_js('sig_onboard_dismissed_transcripts')}
1841: const TR_META = {meta_json};
1842: const _trTextCache = {{}};    // num -> 全文（已完成的下載結果快取，不重複下載）
1843: const _trPending = {{}};      // num -> 進行中的fetch Promise（2026-08-02完工前
1844:                             // Codex最終審查指出：原本只靠_trTextCache擋重複
1845:                             // 下載，但同一個num的fetch還沒resolve前，第二次
1846:                             // 呼叫trFetchOne()看到cache還是undefined，會再送
1847:                             // 一次fetch——尤其trEnsureAllLoaded()一次對679個
1848:                             // num發動Promise.all時，若使用者手滑觸發第二次
1849:                             // 搜尋，兩批Promise.all會互相疊加成上千個並行
1850:                             // 請求。這裡改成同一個num的fetch進行中時直接回傳
1851:                             // 同一個pending promise，不重新發起。
1852: let _trFullLoaded = false;
1853: let _trFullLoadPromise = null;
1854: let _trSearchGen = 0;  // 搜尋世代計數器：避免舊搜尋在使用者已經改了關鍵字之後
1855:                         // 才跑完，用過期結果覆蓋新搜尋的畫面（見trDoSearch()）
1856: 
1857: async function trFetchOne(num) {{
1858:   if (_trTextCache[num] !== undefined) return _trTextCache[num];
1859:   if (_trPending[num]) return _trPending[num];
1860:   const p = (async () => {{
1861:     try {{
1862:       const resp = await fetch('{TRANSCRIPTS_DATA_DIR_NAME}/EP' + num + '.txt');
1863:       if (!resp.ok) {{
1864:         _trTextCache[num] = null;
1865:         return null;
1866:       }}
1867:       const text = await resp.text();
1868:       _trTextCache[num] = text;
1869:       return text;
1870:     }} catch (e) {{
1871:       _trTextCache[num] = null;
1872:       return null;
1873:     }} finally {{
1874:       delete _trPending[num];
1875:     }}
1876:   }})();
1877:   _trPending[num] = p;
1878:   return p;
1879: }}
1880: 
1881: async function trToggle(num) {{
1882:   const body  = document.getElementById('tr-body-' + num);
1883:   const arrow = document.getElementById('tr-arrow-' + num);
1884:   const isOpen = body.style.display !== 'none';
1885:   if (isOpen) {{
1886:     body.style.display = 'none';
1887:     arrow.innerHTML = '&#9656;';
1888:     return;
1889:   }}
1890:   if (!body.dataset.loaded) {{
1891:     body.textContent = '載入中...';
1892:     const text = await trFetchOne(num);
1893:     if (text === null) {{
1894:       body.textContent = '這集逐字稿檔案缺失（transcripts/ 目錄裡找不到對應檔案，可能需要重新下載這一集），不是網頁的錯誤。';
1895:     }} else {{
1896:       body.textContent = text;
1897:     }}
1898:     body.dataset.loaded = '1';
1899:   }}
1900:   body.style.display = '';
1901:   arrow.innerHTML = '&#9662;';
1902: }}
1903: 
1904: async function trEnsureAllLoaded() {{
1905:   if (_trFullLoaded) return;
1906:   if (_trFullLoadPromise) return _trFullLoadPromise;  // 已經有一次全量下載在
1907:                                                         // 跑，共用同一個promise
1908:                                                         // 不重新發起679個請求
1909:   const status = document.getElementById('tr-status');
1910:   status.textContent = '首次搜尋下載全部逐字稿中...';
1911:   _trFullLoadPromise = Promise.all(TR_META.map(m => trFetchOne(m.num))).then(() => {{
1912:     _trFullLoaded = true;
1913:   }});
1914:   await _trFullLoadPromise;
1915: }}
1916: 
1917: let _trSearchTimer = null;
1918: function trOnSearchInput(v) {{
1919:   clearTimeout(_trSearchTimer);
1920:   _trSearchTimer = setTimeout(() => trDoSearch(v), 300);
1921: }}
1922: 
1923: async function trDoSearch(q) {{
1924:   q = q.trim();
1925:   const myGen = ++_trSearchGen;  // 這次搜尋的世代號，跑完後如果已經不是最新
1926:                                   // 世代（使用者又改了關鍵字），就放棄更新畫面
1927:   const status = document.getElementById('tr-status');
1928:   const items = document.querySelectorAll('.tr-item');
1929:   if (!q) {{
1930:     items.forEach(el => el.classList.remove('hidden'));
1931:     document.getElementById('tr-empty').style.display = 'none';
1932:     status.textContent = '共 ' + TR_META.length + ' 集';
1933:     return;
1934:   }}
1935:   const t0 = performance.now();
1936:   await trEnsureAllLoaded();
1937:   if (myGen !== _trSearchGen) return;  // 2026-08-02完工前Codex最終審查指出：
1938:                                          // 舊搜尋在使用者改關鍵字後才跑完，會
1939:                                          // 用過期結果覆蓋新搜尋畫面——這裡擋下
1940:   const ql = q.toLowerCase();
1941:   let matched = 0;
1942:   items.forEach(el => {{
1943:     const num = el.dataset.num;
1944:     const text = (_trTextCache[num] || '').toLowerCase();
1945:     const titleHit = (el.dataset.title || '').includes(ql);
1946:     const hit = titleHit || text.includes(ql);
1947:     el.classList.toggle('hidden', !hit);
1948:     if (hit) matched++;
1949:   }});
1950:   document.getElementById('tr-empty').style.display = matched === 0 ? '' : 'none';
1951:   const dt = Math.round(performance.now() - t0);
1952:   status.textContent = matched + ' / ' + TR_META.length + ' 集符合「' + q + '」（' + dt + 'ms）';
1953: }}
1954: </script>
1955: </body>
1956: </html>"""
1957: 
```

### C-4. 三頁共用元件（nav / onboarding / escape）

```python
20: def _esc(s) -> str:
21:     """2026-08-02 完工前 Codex 覆核指出：generate_html_email() 把 Gemini 分析結果
22:     的 stock_name/stock_code/raw_reason/exact_quote 直接用 f-string 塞進 email
23:     HTML，完全沒有跳脫——詳細版（JS 端 escapeHtml()，見 renderDetailTab()/
24:     renderStockTab()）已經修過同一類問題，這裡是 Python 端另一條輸出路徑，
25:     同樣風險、需要同樣的防護。用 Python 內建 html.escape() 跳脫 & < > " '。"""
26:     return html.escape(str(s or ""))
27: 
28: def _json_for_script(data, **kw) -> str:
29:     """給要塞進 <script> 標籤內的 JSON 字串用，把 '<' 轉成 \\u003c。
30: 
31:     signals_json 裡的 raw_reason/exact_quote 來自 Gemini 分析結果，內容源頭是
32:     Podcast 逐字稿——理論上不是使用者直接輸入，但這份 HTML 最終會被
33:     workflow push 到 GitHub Pages 公開頁面（見 notifier.py 的呼叫端），任何
34:     分析文字若剛好含有字面上的 "</script>"（例如逐字稿裡真的講到這個詞、
35:     或未來換一顆更容易被誘導輸出奇怪內容的模型），沒有跳脫就會提前結束
36:     script 區塊、後面的內容被當成 HTML 解析，等於一個儲存型 XSS 缺口。
37:     跳脫 '<' 不影響 JSON 語義（合法的 JSON 跳脫），瀏覽器解析出來的值
38:     跟原本完全一樣，純粹是防禦，不改變任何功能行為。
39:     2026-08-01 Codex 審查發現，索羅門本地修正。"""
40:     return json.dumps(data, **kw).replace("<", "\\u003c")
41: 
42: 
43: def _ep_num(ep: str) -> int:
44:     m = re.search(r"\d+", ep)
45:     return int(m.group()) if m else 0
46: 
47: 
48: # 三個獨立靜態頁面（報告/關注度/逐字稿）共用的導覽 tab 列（2026-08-02 索羅門
49: # 新增，任務1e）。三頁各自獨立生成（無SPA路由、無共用JS bundle），「分頁籤」
50: # 用「視覺上像tab、實際是三個獨立超連結」實作，href 對應 GitHub Pages 部署後
51: # 的實際檔名（見 .github/workflows/*.yml：report_detail.html→index.html、
52: # report_attention.html→attention.html、report_transcripts.html→
53: # transcripts.html）。用同一個函式產生，避免三處各寫一份風格漂移。
54: # Email版（generate_html_email()）不加這個——Email是獨立情境，比照1e任務檔
55: # 明確排除慣例。
56: _NAV_TABS = (
57:     ("report",      "index.html",       "📊 訊號報告"),
58:     ("attention",   "attention.html",   "🔥 目前關注度"),
59:     ("transcripts", "transcripts.html", "📄 逐字稿"),
60: )
61: 
62: 
63: def _render_nav_tabs(active: str) -> str:
64:     items = "".join(
65:         f'<a href="{href}" class="nav-tab{" nav-tab-active" if key == active else ""}">{label}</a>'
66:         for key, href, label in _NAV_TABS
67:     )
68:     return f'<div class="nav-tabs">{items}</div>'
69: 
70: 
71: _NAV_TABS_CSS = """
72:   .nav-tabs{display:flex;gap:6px;padding:8px 12px;background:#14202b;}
73:   .nav-tab{flex:1;text-align:center;padding:8px 4px;border-radius:6px;font-size:13px;
74:     color:#b3c1cd;text-decoration:none;background:rgba(255,255,255,.06);white-space:nowrap;}
75:   .nav-tab:hover{background:rgba(255,255,255,.12);}
76:   .nav-tab-active{background:#2b6cb0;color:#fff;font-weight:bold;}
77:   @media(max-width:600px){.nav-tab{font-size:11px;padding:7px 2px;}}
78: """
79: 
80: 
81: # 三頁共用的「怎麼看這份報告」新手導覽（2026-08-02 索羅門新增，任務1f）。
82: # 純前端 localStorage 判斷（key 三頁各自獨立，不共用，見下方 storage_key
83: # 參數），不需要後端/DB配合。首次造訪（key 不存在）預設展開；使用者按過
84: # 「關閉」後記住不再自動展開，但保留一個常駐右下角「？」按鈕可隨時重新
85: # 叫出（不會反過來清掉 localStorage，重新整理後仍維持收合，符合任務檔
86: # 完成的定義第2點的兩個獨立驗證點）。
87: _ONBOARD_CSS = """
88:   .onboard-wrap{border-bottom:1px solid #eee;background:#f7fbff;}
89:   .onboard-head{display:flex;align-items:center;gap:8px;padding:10px 16px;font-size:13px;
90:     color:#2b6cb0;font-weight:bold;}
91:   .onboard-body{padding:0 16px 14px;font-size:13px;color:#555;line-height:1.8;}
92:   .onboard-body ul{margin:4px 0 0;padding-left:18px;}
93:   .onboard-dismiss{margin-left:auto;font-weight:normal;color:#8fb3dc;font-size:12px;
94:     cursor:pointer;white-space:nowrap;}
95:   .onboard-dismiss:hover{color:#2b6cb0;}
96:   .onboard-fab{position:fixed;right:16px;bottom:16px;width:34px;height:34px;border-radius:50%;
97:     background:#2b6cb0;color:#fff;align-items:center;justify-content:center;
98:     font-size:16px;font-weight:bold;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.25);
99:     z-index:50;display:none;}
100: """
101: 
102: 
103: def _render_onboarding(storage_key: str, heading: str, bullets: list[str]) -> str:
104:     items = "".join(f"<li>{_esc(b)}</li>" for b in bullets)
105:     return f'''
106:     <div class="onboard-wrap" id="onboard-wrap" style="display:none;">
107:       <div class="onboard-head">
108:         <span>💡 {_esc(heading)}</span>
109:         <span class="onboard-dismiss" onclick="onboardDismiss()">知道了，不用每次都顯示 ✕</span>
110:       </div>
111:       <div class="onboard-body"><ul>{items}</ul></div>
112:     </div>
113:     <div class="onboard-fab" id="onboard-fab" onclick="onboardReopen()" title="重新打開新手導覽">？</div>'''
114: 
115: 
116: def _onboard_js(storage_key: str) -> str:
117:     return f"""
118: const ONBOARD_KEY = {json.dumps(storage_key)};
119: function onboardInit() {{
120:   const dismissed = localStorage.getItem(ONBOARD_KEY) === '1';
121:   document.getElementById('onboard-wrap').style.display = dismissed ? 'none' : '';
122:   document.getElementById('onboard-fab').style.display = dismissed ? 'flex' : 'none';
123: }}
124: function onboardDismiss() {{
125:   localStorage.setItem(ONBOARD_KEY, '1');
126:   document.getElementById('onboard-wrap').style.display = 'none';
127:   document.getElementById('onboard-fab').style.display = 'flex';
128: }}
129: function onboardReopen() {{
130:   document.getElementById('onboard-wrap').style.display = '';
131:   document.getElementById('onboard-fab').style.display = 'none';
132: }}
133: document.addEventListener('DOMContentLoaded', onboardInit);
134: """
135: 
136: 
```

## D. 專案檔案清單（讓你知道還有什麼存在、但這次沒附上）


```
analyzer.py
attention.py
backup_db.py
batch.py
build_idiom_glossary.py
config.py
crosscheck.py
database.py
download_transcripts.py
episodes.json
independent_transcribe.py
line_query.py
main.py
migrate.py
migrate_to_neon.py
notifier.py
performance.py
prices.py
prompt.py
report.py
report_html.py
restore_db.py
show_latest.py
split_sentinel.py
stock_dict.py
sync_independent_transcripts.py
update.py
welcome_email.py
```

## E. 你的任務

請針對**第二頁與第三頁**做獨立審查，重點是「陌生訪客第一次看到這兩頁時，能不能看懂、會不會誤解、想做的下一件事做不做得到」。

請回答：

1. **第二頁最嚴重的問題是什麼**（只挑一個，講清楚為什麼是它）。
2. **第二頁其餘問題**，依嚴重度排序，每項要有：問題／為什麼是問題／具體怎麼改（能落地的程度）。
3. **第三頁同上**（最嚴重一個 + 其餘排序）。
4. **正確性 bug**（不是體感問題，是會算錯或顯示錯的）：有就列，沒有就明講沒有。
5. **你認為不該改的東西**：有沒有哪些看起來像問題、但其實現在這樣是對的？

限制與要求：
- 不要建議「加一個 AI 聊天框」「接推播」這類跨出靜態網站範圍的東西。這是 GitHub Pages 靜態站，
  資料每週由排程重新產生，沒有後端、沒有登入、沒有資料庫查詢 API。
- 改動建議要能落在現有的 Python 產生 HTML 的架構裡。
- **請主動挑戰**：如果你覺得這兩頁的整個資訊架構就是錯的，直接講，不要只在細節上打轉。
- 附行號佐證。不要臆測沒附上的檔案內容，需要看什麼就明講「需要看 X」。
