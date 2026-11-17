#!/usr/bin/env python3
"""配音（本机 BreezeCast · BreezeTTS 2 设计音色）+ 逐字对齐与回读校验（本机 Murmur · Qwen3-ASR）。

用法：
    python3 scripts/tts_breeze.py <narration.json> <输出目录> [--gap 0.8] [--lead 0.6] [--voice 音色名] [--style "…"] [--qa] [--reuse] [--jobs 1]

narration.json 与 tts.py 相同：{"voice": {...}, "lexicon": {...}, "beats": [{"id", "narration"}]}，旁白里用 [[cue]] 标时刻。
voice 写 {"engine": "breeze", "voice": "AI博主沉稳男声", "style": "讲课语气说明"}，可选 "params": {"seed": 7}（BreezeCast 采样参数原样透传）、"lang": "en"；命令行参数优先。
voice 是 BreezeCast 里已保存的音色（名字或 id）。用 voice_audition.py 设计、试听、--save 保存：保存的那条试听成了音色的参照录音，
整套课每一拍听起来都是同一个人。自己的声音先在 BreezeCast 里克隆成音色，再把名字写进来。
style 作为 instruct 发给 BreezeCast（Voice Direction：语气、语速、情绪），要和旁白同一种语言。

BreezeCast 要开着（引擎 ready、装好 BreezeTTS 2 模型）。本机自动发现；局域网里另一台 Mac：export BREEZECAST_URL=http://<IP>:17860。不需要任何密钥。
BreezeCast 不返回逐词时间，所以每一拍整段合成（语调自然），再让本机 Murmur 转写一遍取逐字时间，按字符对齐回原文。
Murmur 要在本机开着、打开 API 服务（默认 7895 端口），当前模型要能给逐字时间（Qwen3-ASR）。每拍转写都会进 Murmur 的历史记录。
输出与 tts.py 一致：<out>/audio/<beat>.mp3、<out>/narration.wav、<out>/timings.json；
timings 里每拍的 words 是逐字的 {text, start, end, i0, i1}，另有 chars（每个字的开始时刻），cues 是绝对秒。
--qa：把同一次 Murmur 转写（不看原文，听到什么写什么）和原文比对，报出读错的地方。
--jobs：同时提交几拍（默认 1；本机引擎一次只算一条，多提交只是排队）。
--reuse：已有的 audio/<beat>.wav 一律不重新合成，只重新对齐（改对齐逻辑时用）。
默认也会复用：同一拍的音色、语气、参数、文字都没变时直接用上次的录音（audio/<beat>.key 记着指纹）。
"""
import hashlib
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CUE_RE = re.compile(r"\[\[([a-z][a-z0-9_-]*)\]\]")
PUNCT = set("，。！？；：、,.!?;:（）()「」『』“”\"'《》…—- 　")
MURMUR_DISCOVERY = Path.home() / "Library/Application Support/app.murmur.asr/api.json"
DEFAULT_VOICE = "AI博主沉稳男声"
DEFAULT_STYLE = "像老师给学生讲一个有意思的小故事：亲切、自然、带一点好奇，语速适中，句子之间自然停顿。"
DISCOVERY = Path.home() / "Library/Application Support/com.breezecast.studio/api.json"


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


# ---- BreezeCast 本机 API（无鉴权，文档见 breezecast skill 的 reference/api.md）----

class BreezeError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code


_BASE = []


def base_url():
    if not _BASE:
        url = os.environ.get("BREEZECAST_URL")
        if not url and DISCOVERY.exists():
            url = json.loads(DISCOVERY.read_text())["base_url"]
        if not url:
            sys.exit("BreezeCast 没在运行：先打开 BreezeCast（另一台 Mac 上的就设 BREEZECAST_URL=http://<IP>:17860）")
        _BASE.append(url.rstrip("/"))
    return _BASE[0]


def api(method, path, body=None, timeout=1800):
    req = urllib.request.Request(base_url() + "/api/v1" + path, method=method, headers={"Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except ValueError:
            err = {}
        raise BreezeError(err.get("code", e.code), err.get("message", e.reason)) from None
    except urllib.error.URLError as e:
        sys.exit(f"连不上 BreezeCast（{base_url()}）：{e.reason}。先打开 BreezeCast")


def check_ready():
    s = api("GET", "/status", timeout=10)
    for _ in range(60):
        if s["engine"]["state"] != "starting":
            break
        time.sleep(5)
        s = api("GET", "/status", timeout=10)
    if s["engine"]["state"] != "ready":
        sys.exit(f"BreezeCast 引擎没就绪（{s['engine']['state']}）：{s['engine'].get('message') or '在 BreezeCast 里重启引擎'}")
    if not s["model"]["installed"]:
        sys.exit("BreezeCast 还没装 BreezeTTS 2 模型：在 BreezeCast 里下载（默认 breeze_tts_2_q8_0，5.1 GB）")


def find_voice(name):
    voices = api("GET", "/voices", timeout=30)
    v = next((v for v in voices if v["id"] == name), None) or next((v for v in voices if v["name"] == name), None)
    if not v:
        have = "、".join(x["name"] for x in voices) or "（空）"
        sys.exit(f"BreezeCast 里没有音色「{name}」（现有：{have}）。先设计并保存：python3 scripts/voice_audition.py <voices.json> <试听目录>，"
                 f"挑一条后加 --save <试听 id> --name {name}")
    if not v["has_reference"]:
        print(f"⚠ 音色「{v['name']}」没有参照录音（纯描述设计），每一拍音色会不一样；用 voice_audition.py --save 存一条试听再用", file=sys.stderr)
    return v


def speak(text, voice_id=None, instruct="", lang="zh", params=None):
    """合成一条，返回 Clip（音频在 clip.path / clip.url）。引擎正在启动就等一会再试。"""
    body = {"text": text, "language": lang, "params": params or {}}
    if voice_id:
        body["voice_id"] = voice_id
    if instruct:
        body["instruct"] = instruct
    for k in range(60):
        try:
            return api("POST", "/speech", body)
        except BreezeError as e:
            if e.code != "engine_starting" or k == 59:
                raise
            time.sleep(5)


def save_clip(clip, dest):
    """Clip 的 WAV 存到 dest：BreezeCast 在本机就直接拷文件，在别的 Mac 上就按 url 下载。"""
    if Path(clip["path"]).exists():
        shutil.copy(clip["path"], dest)
    else:
        with urllib.request.urlopen(clip["url"], timeout=600) as r:
            Path(dest).write_bytes(r.read())


# ---- 文本处理与对齐 ----

def strip_cues(text):
    out, cues, pos = [], {}, 0
    for m in CUE_RE.finditer(text):
        out.append(text[pos:m.start()])
        cues[m.group(1)] = sum(len(p) for p in out)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), cues


# 全由罗马数字字母组成的大写缩写容易被当罗马数字念：CLI→151、MD→1500、CC→200、LM→950。拆成单个字母就会逐个字母念
ROMANISH = re.compile(r"(?<![A-Za-z])[IVXLCDM]{2,4}(?![A-Za-z])")


def apply_lexicon(text, lexicon):
    for k in sorted(lexicon or {}, key=len, reverse=True):
        text = text.replace(k, lexicon[k])
    return text if LANG == "en" else ROMANISH.sub(lambda m: " ".join(m.group(0)), text)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


LANG = "zh"   # narration.json 的 voice.lang；"en" = 英文课


# ---- Murmur 本机 API（无鉴权，文档见 Murmur 仓库 skills/murmur-asr/references/api.md）----

_MURMUR = {}


def murmur_call(method, path, body=None, timeout=600):
    url = json.loads(MURMUR_DISCOVERY.read_text())["baseUrl"] if MURMUR_DISCOVERY.exists() else "http://127.0.0.1:7895"
    req = urllib.request.Request(url.rstrip("/") + path, method=method, headers={"Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", e.reason)
        except ValueError:
            msg = e.reason
        raise RuntimeError(f"Murmur {path}：{msg}") from None
    except urllib.error.URLError as e:
        sys.exit(f"连不上 Murmur（{url}）：{e.reason}。打开 Murmur，在「API 接口」页启用 API 服务")


def murmur_check():
    h = murmur_call("GET", "/health", timeout=10)
    m = h.get("model")
    if not h.get("ok") or not m:
        sys.exit(f"Murmur 没就绪：{(h.get('engine') or {}).get('error') or '在 Murmur 的「模型」页下载并加载 Qwen3-ASR'}")
    if not m.get("wordTimestamps"):
        sys.exit(f"Murmur 当前模型 {m['id']} 不给逐字时间，对不了齐：在 Murmur 里换成 Qwen3-ASR")
    want = "Chinese" if LANG == "zh" else "English"
    _MURMUR["language"] = want if m.get("acceptsLanguage") and want in m.get("languages", []) else None


def murmur_transcribe(wav):
    """一拍音频 → (逐字 [(字, 开始, 结束)], 全文)。Murmur 和本脚本在同一台 Mac 上，直接传路径，不上传。"""
    body = {"path": str(Path(wav).resolve()), "title": f"tts_breeze {Path(wav).stem}", "format": "json"}
    if _MURMUR.get("language"):
        body["language"] = _MURMUR["language"]
    d = murmur_call("POST", "/transcribe", body)
    chars = [(ch, w["start"], w["end"]) for seg in d["segments"] for w in seg.get("words", []) for ch in w["text"] if not ch.isspace()]
    return chars, d.get("text", "")


def norm(ch):
    return ch.lower()


def align(text, wch, dur):
    """原文每个字的开始时刻（相对本拍）。能对上的用 Murmur 逐字时间，对不上的在前后已知点之间按位置插值。"""
    idx = [i for i, c in enumerate(text) if c not in PUNCT and not c.isspace()]
    a = [norm(text[i]) for i in idx]
    b = [norm(c) for c, _, _ in wch if c not in PUNCT]
    bt = [t0 for c, t0, _ in wch if c not in PUNCT]
    known = {}
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            known[blk.a + k] = bt[blk.b + k]
    # 单调化：识别时间偶尔回跳
    last = 0.0
    for k in sorted(known):
        known[k] = max(known[k], last)
        last = known[k]
    anchors = [(-1, 0.0)] + sorted(known.items()) + [(len(a), dur)]
    times = [0.0] * len(a)
    for (k0, t0), (k1, t1) in zip(anchors, anchors[1:]):
        for k in range(k0 + 1, k1):
            times[k] = t0 + (t1 - t0) * (k - k0) / (k1 - k0)
        if 0 <= k1 < len(a):
            times[k1] = t1
    start = [0.0] * len(text)
    j = 0
    for i, c in enumerate(text):
        if j < len(idx) and idx[j] == i:
            start[i] = times[j]
            j += 1
        else:  # 标点、空格：跟在前一个字后面
            start[i] = start[i - 1] if i else 0.0
    return start, len(known) / max(1, len(a))


CN_NUM = str.maketrans("零〇一二三四五六七八九", "00123456789")


def qa_diff(text, heard):
    """回读比对：去掉标点、统一数字写法后比，返回 (相似度, 差异片段)"""
    f = lambda s: [c for c in s.lower().translate(CN_NUM) if c not in PUNCT and not c.isspace()]
    a, b = f(text), f(heard.replace("做", "作"))
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    diffs = [("".join(a[i1:i2]), "".join(b[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    return sm.ratio(), diffs


def cn_value(tok):
    """「六万三千八百四十」→ 63840；纯数字串（含「一五五」这种逐位念）按位拼；认不出返回 None"""
    t = tok.translate(CN_NUM)
    if t.isdigit():
        return int(t)
    total, sec, num = 0, 0, 0
    for c in t:
        if c.isdigit():
            num = int(c)
        elif c in "十百千":
            sec += (num or 1) * {"十": 10, "百": 100, "千": 1000}[c]; num = 0
        elif c == "万":
            total += (sec + num) * 10000; sec = num = 0
    return total + sec + num


def odd_numbers(text, heard):
    """回读里冒出原文没有的数字 = 多半念错了（例如 CLI 被当罗马数字念成「一百五十一」、AGENTS.MD 念成「一千五百」）"""
    src = {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text)}
    src |= {v for x in re.findall(r"[零〇一二三四五六七八九十百千万]+", text) if (v := cn_value(x)) is not None}
    bad = []
    for m in re.finditer(r"[0-9零〇一二三四五六七八九十百千万]{2,}", heard):
        v = cn_value(m.group(0))
        if v is not None and v not in src and v >= 100:
            bad.append(m.group(0))
    return bad


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    gap = float(arg("--gap", 0.8))
    lead = float(arg("--lead", 0.6))
    jobs = int(arg("--jobs", 1))
    data = json.loads(src.read_text(encoding="utf-8"))
    vcfg = data.get("voice", {}) if data.get("voice", {}).get("engine") == "breeze" else {}
    global LANG
    LANG = data.get("voice", {}).get("lang", "zh")
    style = arg("--style", vcfg.get("style", DEFAULT_STYLE))
    params = vcfg.get("params", {})
    check_ready()
    murmur_check()
    voice = find_voice(arg("--voice", vcfg.get("voice", DEFAULT_VOICE)))
    lexicon = data.get("lexicon", {})
    (out / "audio").mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    # 每一拍的准备：文字、cue 位置、缓存指纹（音色 id 变了 = 重新保存过音色，要重配）
    jobs_list = []
    for b in data["beats"]:
        clean, cue_pos = strip_cues(b["narration"])
        say = apply_lexicon(clean, lexicon)
        digest = hashlib.md5(json.dumps(["breeze", voice["id"], style, params, LANG, say], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        jobs_list.append({"b": b, "clean": clean, "cue_pos": cue_pos, "say": say, "digest": digest,
                          "wav": out / "audio" / f"{b['id']}.wav", "mp3": out / "audio" / f"{b['id']}.mp3", "meta": out / "audio" / f"{b['id']}.key"})

    # 第一步：合成。音色、语气、参数、文字都没变的拍直接复用上次的录音
    def synth(j):
        t0 = time.time()
        reuse = j["wav"].exists() and ("--reuse" in sys.argv or (j["meta"].exists() and j["meta"].read_text() == j["digest"]))
        if not reuse:
            clip = speak(j["say"], voice["id"], style, LANG, params)
            raw = j["wav"].with_suffix(".raw.wav")
            save_clip(clip, raw)
            # 去掉首尾静音，节奏由 gap 控制
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse",
                            "-ar", "48000", "-ac", "1", str(j["wav"])], check=True)
            raw.unlink()
            j["meta"].write_text(j["digest"])
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(j["wav"]), "-b:a", "160k", str(j["mp3"])], check=True)
        j["dur"], j["reused"], j["synth_s"] = probe(j["wav"]), reuse, time.time() - t0

    # 第二步（顺序）：Murmur 转写一遍，逐字对齐；同一次转写也用来回读
    def align_one(j):
        chars, heard = murmur_transcribe(j["wav"])
        j["rel"], j["cover"] = align(j["clean"], chars, j["dur"])
        if "--qa" in sys.argv:
            j["qa"] = (heard, *qa_diff(j["clean"], heard))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(synth, jobs_list))
    for j in jobs_list:  # Murmur 一次只跑一个任务，并行只是排队
        align_one(j)

    # 第三步（顺序）：按时长排出绝对时间
    timings = {"voice": {"engine": "breeze", "voice": voice["name"], "voice_id": voice["id"], "style": style, **({"params": params} if params else {})}, "beats": {}}
    t, parts, report = lead, [], []
    for j in jobs_list:
        b, clean, dur = j["b"], j["clean"], j["dur"]
        starts = [round(t + x, 3) for x in j["rel"]]
        words = []
        if LANG == "en":   # 英文按词：一个词一个时间段（字幕按词断行、小人按词张嘴）
            for m in re.finditer(r"[A-Za-z0-9](?:[A-Za-z0-9'’\-]|\.(?=[A-Za-z0-9]))*", clean):
                i, i1 = m.start(), m.end()
                nxt = next((starts[k] for k in range(i1, len(clean)) if starts[k] > starts[i] and clean[k].isalnum()), round(t + dur, 3))
                words.append({"text": m.group(0), "start": starts[i], "end": min(nxt, round(t + dur, 3)), "i0": i, "i1": i1})
        for i, ch in enumerate(clean if LANG == "zh" else ""):
            if ch.isspace() or ch in PUNCT:
                continue
            nxt = next((starts[k] for k in range(i + 1, len(clean)) if starts[k] > starts[i]), round(t + dur, 3))
            words.append({"text": ch, "start": starts[i], "end": min(nxt, round(t + dur, 3)), "i0": i, "i1": i + 1})
        cues = {name: next((w["start"] for w in words if w["i0"] >= k and clean[w["i0"]] not in PUNCT), round(t + dur, 3)) for name, k in j["cue_pos"].items()}
        timings["beats"][b["id"]] = {"file": f"audio/{b['id']}.mp3", "text": clean, "start": round(t, 3), "end": round(t + dur, 3),
                                     "duration": round(dur, 3), "words": words, "chars": starts, "cues": cues, "align": round(j["cover"], 3)}
        status = "复用" if j["reused"] else f"合成 {j['synth_s']:.1f}s"
        line = f"{b['id']}  {dur:5.2f}s  {len(clean):3d} 字  {len(clean) / dur:.2f} 字/秒  对齐 {j['cover']:.0%}  {status}"
        if "qa" in j:
            heard, ratio, diffs = j["qa"]
            odd = odd_numbers(clean, heard)
            line += f"  回读 {ratio:.0%}" + (f"  差异 {diffs[:4]}" if diffs else "") + (f"  ⚠ 可疑读数 {odd}" if odd else "")
            report.append({"beat": b["id"], "heard": heard, "ratio": round(ratio, 3), "diffs": diffs, **({"odd_numbers": odd} if odd else {})})
        print(line)
        parts.append((j["mp3"], t))
        t += dur + max(gap, b.get("gap", 0), b.get("min_hold_s", 0))
    total = round(t - gap + lead, 3)
    timings["total"] = total

    inputs, filters = [], []
    for i, (mp3, start) in enumerate(parts):
        inputs += ["-i", str(mp3)]
        filters.append(f"[{i}:a]aresample=48000,adelay={int(start * 1000)}:all=1[a{i}]")
    mixin = "".join(f"[a{i}]" for i in range(len(parts)))
    filters.append(f"{mixin}amix=inputs={len(parts)}:normalize=0,apad=whole_dur={total},atrim=0:{total}[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-ac", "1", "-ar", "48000", str(out / "narration.wav")], check=True)
    (out / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=1), encoding="utf-8")
    if report:
        (out / "qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    odd = [r["beat"] for r in report if r.get("odd_numbers")]
    if odd:
        print(f"⚠ 这几拍回读出现原文没有的数字，先听一下：{'、'.join(odd)}（数字、缩写在 lexicon 里写成读法，例如 GPU → G P U、3.5% → 百分之三点五）")
    print(f"合计 {total:.2f}s → {out / 'timings.json'}（用时 {time.time() - t_start:.0f}s，并行 {jobs}）")


if __name__ == "__main__":
    main()
