# -*- coding: utf-8 -*-
"""依 692 份真實逐字稿的出現份數重建熱詞檔，並實測 token 數塞滿 224 上限。"""
import json, re, sys
from pathlib import Path
import tokenizers, huggingface_hub

ROOT = Path(r"D:\All claude\300_Projects\stock-signal")
TRANS = sorted(ROOT.glob("transcripts/EP*.md"))

# 1) 候選池 A：節目與總經固定會講、但不在台股名冊裡的詞（人工挑，來源是節目性質）
POOL_A = """股癌 謝孟恭 聯準會 輝達 特斯拉 那斯達克 費半 標普 道瓊 超微 博通 美光
英特爾 甲骨文 鮑爾 台積電""".split()

# 2) 候選池 B：台股名冊（長度>=3），避免兩字詞誤命中日常用語
lm = json.loads((ROOT / "tw_listing_map.json").read_text(encoding="utf-8"))
def walk(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and len(v) >= 2: out.add(v)
            walk(v, out)
    elif isinstance(o, list):
        for v in o: walk(v, out)
names = set(); walk(lm, names)
POOL_B = sorted(n for n in names if len(n) >= 3 and not re.search(r"[0-9A-Za-z]{4,}", n))

# 3) 候選池 C：兩字大型股白名單（人工挑，只放在節目語境下不會誤解的）
POOL_C = """鴻海 廣達 緯創 聯電 華碩 台塑 中鋼 群創 友達 南亞 長榮 陽明 萬海 國巨
智邦 京元 力成 瑞昱 聯詠 矽力 光洋 世芯 大摩 高盛""".split()

# 4) 用真實逐字稿量「出現在幾份」
texts = [p.read_text(encoding="utf-8", errors="ignore") for p in TRANS]
print(f"母體：{len(texts)} 份逐字稿", flush=True)

def docfreq(w):
    return sum(1 for t in texts if w in t)


# 黑名單：這些名稱是被「字串包含」誤算的日常用語，不是真的在講該公司
BLOCK = set("""創業家 地心引力 大台北 大魯閣 八方雲集 三商家購 台灣大 新天地 幸福
大成鋼 太空梭 全球傳動 第一店 大學光 好樂迪 愛之味""".split())

cand = []
seen = set()
for w in POOL_A + POOL_C + POOL_B:
    if w in BLOCK: continue
    if w in seen: continue
    seen.add(w)
    cand.append((w, docfreq(w)))

# 5) 門檻：至少出現在 8 份（約 1%）才有資格；A 池固定保留（節目專名，漏標成本高）
core = [w for w in POOL_A if w in seen]
ranked = sorted([(w, c) for w, c in cand if c >= 8 and w not in POOL_A],
                key=lambda x: -x[1])

# 6) 實測 token 數，塞滿 224
tj = huggingface_hub.hf_hub_download("Systran/faster-whisper-large-v3", "tokenizer.json")
tk = tokenizers.Tokenizer.from_file(tj)
def ntok(words): return len(tk.encode(" ".join(words), add_special_tokens=False).ids)

final = []
for w in core + [w for w, _ in ranked]:
    trial = final + [w]
    if ntok(trial) > 224: continue   # 塞不下就跳過，繼續試下一個較短的
    final = trial

out = " ".join(final)
print(f"候選 {len(cand)} 個 → 過門檻 {len(core)+len(ranked)} 個 → 實際塞入 {len(final)} 個，token={ntok(final)}/224")
print("內容：", out)
Path(sys.argv[1]).write_text(out + "\n", encoding="utf-8")
