# -*- coding: utf-8 -*-
"""股癌官方 RSS → 依集號取得 <enclosure> mp3 → 下載。

為什麼要有這支（2026-08-24）：
  舊路徑是拿 YouTube 影片下載整支影片，會被 403 擋、檔案大一個數量級，而且 YouTube
  的集號是我們自己從標題湊的。官方 RSS 的集號是節目方自己編的，最可靠。

⚠️ 集號對應是「驗過的」不是「假設的」：
  RSS 的 <title> 形如 "EP690 | ⛳"，集號取自標題開頭的 EPnnn；episodes.json 的集號是
  `number` 欄位。兩邊用 pubDate/date 交叉核對（見 verify_mapping()），核對不過就報錯，
  不會默默拿錯集。RSS pubDate 是 GMT、episodes.json 的 date 來源不明（疑似上架當地日），
  所以容忍 ±1 天。

這支是**新增檔案**，不改任何既有流程；既有呼叫端（independent_transcribe.py 等）
完全不受影響。

用法：
  python gooaye_rss.py --list                       # 列出 RSS 有幾集、集號範圍
  python gooaye_rss.py --verify                     # 跟 episodes.json 交叉核對日期
  python gooaye_rss.py --ep 684 --out D:\tmp        # 下載 EP684 的 mp3
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

RSS_URL = "https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml"
HERE = Path(__file__).resolve().parent
EPISODES_JSON = HERE / "episodes.json"
UA = "Mozilla/5.0 (compatible; gooaye-rss/1.0)"

_EP_RE = re.compile(r"^\s*EP\s*(\d+)", re.IGNORECASE)


def log(msg: str):
    print(msg, flush=True)


def fetch_rss(cache: Path | None = None, max_age_hours: float = 6.0) -> bytes:
    """抓 RSS；給 cache 路徑時，夠新就直接用快取（避免反覆打人家的伺服器）。"""
    if cache and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < max_age_hours * 3600:
            log(f"[rss] 用快取 {cache}（{age/3600:.1f} 小時前）")
            return cache.read_bytes()
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"RSS 取得失敗 http={r.status}")
        data = r.read()
    log(f"[rss] 下載 {len(data)/1e6:.1f} MB")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    return data


def parse_episodes(raw: bytes) -> dict[int, dict]:
    """回傳 {集號: {title, mp3, pub_dt, guid}}。同集號重複出現會報錯，不默默覆蓋。"""
    root = ET.fromstring(raw)
    out: dict[int, dict] = {}
    unnumbered = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        m = _EP_RE.match(title)
        if not m:
            unnumbered.append(title)
            continue
        n = int(m.group(1))
        enc = item.find("enclosure")
        if enc is None or not enc.get("url"):
            raise RuntimeError(f"EP{n} 沒有 <enclosure> mp3 直連：{title!r}")
        pub = item.findtext("pubDate")
        pub_dt = parsedate_to_datetime(pub) if pub else None
        rec = {"title": title, "mp3": enc.get("url"),
               "length": int(enc.get("length") or 0),
               "pub_dt": pub_dt, "guid": item.findtext("guid")}
        if n in out:
            raise RuntimeError(f"RSS 裡 EP{n} 出現兩次，集號不唯一，需人工確認："
                               f"{out[n]['title']!r} vs {title!r}")
        out[n] = rec
    if unnumbered:
        log(f"[rss] {len(unnumbered)} 個 item 標題開頭不是 EPnnn，已跳過：{unnumbered[:5]}")
    return out


def load_local_episodes() -> dict[int, dict]:
    import json
    if not EPISODES_JSON.exists():
        return {}
    data = json.loads(EPISODES_JSON.read_text(encoding="utf-8"))
    return {int(e["number"]): e for e in data if e.get("number") is not None}


def verify_mapping(rss: dict[int, dict], local: dict[int, dict],
                   sample: list[int] | None = None, tolerance_days: int = 1) -> list[str]:
    """交叉核對集號↔日期。回傳問題清單（空的代表核對通過）。"""
    problems = []
    keys = sample if sample else sorted(set(rss) & set(local))
    for n in keys:
        if n not in rss:
            problems.append(f"EP{n}: RSS 裡沒有")
            continue
        if n not in local:
            problems.append(f"EP{n}: episodes.json 裡沒有")
            continue
        pub = rss[n]["pub_dt"]
        d = local[n].get("date")
        if not pub or not d:
            problems.append(f"EP{n}: 缺日期（rss={pub} local={d}）")
            continue
        ld = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        delta = abs((pub.astimezone(timezone.utc).date() - ld.date()).days)
        if delta > tolerance_days:
            problems.append(f"EP{n}: RSS {pub.date()} vs episodes.json {d}，差 {delta} 天")
    return problems


def download_mp3(rec: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(rec["mp3"], headers={"User-Agent": UA})
    t0 = time.time()
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        if r.status != 200:
            raise RuntimeError(f"mp3 下載失敗 http={r.status}")
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(out_path)
    size = out_path.stat().st_size
    log(f"[mp3] {out_path.name} {size/1e6:.1f} MB，耗時 {time.time()-t0:.0f}s")
    if rec.get("length") and abs(size - rec["length"]) > max(1024, rec["length"] * 0.01):
        log(f"[mp3][警告] 實際大小 {size} 與 RSS 宣告的 length {rec['length']} 不符")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="股癌官方 RSS mp3 取得器")
    ap.add_argument("--ep", type=int, default=None, help="要下載的集號")
    ap.add_argument("--out", default=".", help="輸出資料夾")
    ap.add_argument("--list", action="store_true", dest="do_list")
    ap.add_argument("--verify", action="store_true", help="跟 episodes.json 全量交叉核對日期")
    ap.add_argument("--verify-sample", default="", help="只核對這幾集，逗號分隔（例 684,600,1）")
    ap.add_argument("--cache", default=str(HERE / "_cache" / "gooaye_rss.xml"))
    ap.add_argument("--no-verify", action="store_true",
                    help="下載前不做集號核對（不建議）")
    args = ap.parse_args()

    raw = fetch_rss(Path(args.cache) if args.cache else None)
    rss = parse_episodes(raw)
    local = load_local_episodes()

    if args.do_list:
        ks = sorted(rss)
        log(f"RSS 可用集數 {len(ks)}，範圍 EP{ks[0]}～EP{ks[-1]}；"
            f"episodes.json 有 {len(local)} 集")
        missing = sorted(set(ks) - set(local))
        extra = sorted(set(local) - set(ks))
        log(f"RSS 有但 episodes.json 沒有：{missing}")
        log(f"episodes.json 有但 RSS 沒有：{extra}")

    sample = [int(x) for x in args.verify_sample.split(",") if x.strip()]
    if args.verify or sample:
        probs = verify_mapping(rss, local, sample or None)
        if probs:
            log(f"[verify] {len(probs)} 個對不上：")
            for p in probs[:40]:
                log("  " + p)
        else:
            n = len(sample) if sample else len(set(rss) & set(local))
            log(f"[verify] {n} 集集號↔日期核對通過（容忍 ±1 天）")

    if args.ep is not None:
        if args.ep not in rss:
            raise SystemExit(f"RSS 裡找不到 EP{args.ep}")
        if not args.no_verify and args.ep in local:
            probs = verify_mapping(rss, local, [args.ep])
            if probs:
                raise SystemExit("集號核對不過，拒絕下載：" + "；".join(probs))
            log(f"[verify] EP{args.ep} 集號↔日期核對通過")
        rec = rss[args.ep]
        log(f"EP{args.ep} 標題: {rec['title']}  pubDate={rec['pub_dt']}")
        out = Path(args.out).expanduser() / f"EP{args.ep}.mp3"
        download_mp3(rec, out)
        log(str(out))


if __name__ == "__main__":
    sys.exit(main())
