#!/usr/bin/env python3
"""配音试听：在本机 BreezeCast 里按描述设计音色（或用已保存的音色）把同一段话读几遍，给每条算几个客观指标；挑中的那条存成音色。

用法：
    python3 scripts/voice_audition.py <voices.json> <输出目录> [--ref 参照试听id]
    python3 scripts/voice_audition.py <voices.json> <输出目录> --save <试听id> --name <音色名>

voices.json：
{"text": "要读的一段话", "lang": "zh",
 "voices": [
   {"id": "host", "name": "男科普博主", "design": "音色描述（和 text 同一种语言）", "takes": 3},
   {"id": "host-lesson", "name": "已存音色 · 讲课语气", "voice": "AI博主沉稳男声", "style": "语气说明"}
 ]}
design：纯描述设计，每条试听音色都不一样（takes 条 → <id>-1 … <id>-N；takes 默认 1 → <id>）。
voice：BreezeCast 里已保存的音色（名字或 id），style 是这一条的语气指导。
已经生成过的（输出目录里有 <id>.wav）不重复调用。试听对应的 BreezeCast clip 记在 clips.json。

--save：把一条设计试听存成 BreezeCast 音色。这条录音成了音色的参照，之后每次合成都是同一个人；
narration.json 里写 "voice": {"engine": "breeze", "voice": "<音色名>", …}。同名音色已存在就不覆盖。

输出：<id>.wav、<id>.mp3（响度归一），metrics.json：
  时长、字/秒、基频中位（判断男女声）、语调起伏（半音标准差）、
  与参照试听的音色相似度（平均对数梅尔谱的余弦相似度，用来比较几条设计试听像不像）。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts_breeze import api, check_ready, find_voice, save_clip, speak  # noqa: E402


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def take_ids(v):
    n = int(v.get("takes", 1)) if v.get("design") else 1
    return [v["id"]] if n == 1 else [f"{v['id']}-{k}" for k in range(1, n + 1)]


def pcm(path, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def f0_track(x, sr=16000, fmin=70, fmax=400, hop=160, win=640):
    out = []
    w = np.hanning(win)
    for i in range(0, len(x) - win, hop):
        fr = x[i:i + win] * w
        if np.sqrt(np.mean(fr ** 2)) < 0.02:
            continue
        ac = np.correlate(fr, fr, "full")[win - 1:]
        lo, hi = sr // fmax, sr // fmin
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] / (ac[0] + 1e-9) > 0.45:
            out.append(sr / k)
    return np.array(out)


def mel_profile(x, sr=16000, n_fft=512, hop=160, n_mels=40):
    """有声帧的平均对数梅尔谱，当作「音色指纹」"""
    frames = np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop] * np.hanning(n_fft)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    energy = spec.sum(1)
    spec = spec[energy > np.percentile(energy, 40)]
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    pts = 700 * (10 ** (np.linspace(mel(80), mel(7600), n_mels + 2) / 2595) - 1)
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        fb[m - 1, a:b] = (np.arange(a, b) - a) / max(1, b - a)
        fb[m - 1, b:c] = (c - np.arange(b, c)) / max(1, c - b)
    prof = np.log(spec @ fb.T + 1e-10).mean(0)
    return prof - prof.mean()


def save_voice(out, take, name):
    clips = json.loads((out / "clips.json").read_text(encoding="utf-8")) if (out / "clips.json").exists() else {}
    c = clips.get(take)
    if not c or not c.get("design"):
        sys.exit(f"clips.json 里没有设计试听「{take}」：只有 design 条目生成的试听能存成音色（已有：{'、'.join(k for k, v in clips.items() if v.get('design')) or '无'}）")
    check_ready()
    if any(v["name"] == name for v in api("GET", "/voices", timeout=30)):
        sys.exit(f"BreezeCast 里已有音色「{name}」，不覆盖；换个名字，或先在 BreezeCast 里删掉旧的")
    v = api("POST", "/voices", {"name": name, "description": f"voice_audition 试听 {take}", "instruct": c["design"], "from_clip_id": c["clip_id"]})
    print(f"✓ 已存音色「{v['name']}」（{v['id']}，参照录音 {'有' if v['has_reference'] else '无'}）→ narration.json 写 \"voice\": {{\"engine\": \"breeze\", \"voice\": \"{v['name']}\", …}}")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    if "--save" in sys.argv:
        if not arg("--name"):
            sys.exit("--save 要配 --name <音色名>")
        return save_voice(out, arg("--save"), arg("--name"))
    text, lang = spec["text"], spec.get("lang", "zh")
    clips_path = out / "clips.json"
    clips = json.loads(clips_path.read_text(encoding="utf-8")) if clips_path.exists() else {}
    todo = [v for v in spec["voices"] if not all((out / f"{i}.wav").exists() for i in take_ids(v))]
    if todo:
        check_ready()
    for v in todo:
        ids = take_ids(v)
        t0 = time.time()
        if v.get("design"):
            takes = api("POST", "/voices/audition", {"instruct": v["design"], "text": text, "language": lang, "count": len(ids), "params": v.get("params", {})})["takes"]
        else:
            takes = [speak(text, find_voice(v["voice"])["id"], v.get("style", ""), lang, v.get("params"))]
        for i, clip in zip(ids, takes):
            save_clip(clip, out / f"{i}.wav")
            clips[i] = {"clip_id": clip["id"], "seed": clip["seed"], **({"design": v["design"]} if v.get("design") else {"voice": v["voice"], "style": v.get("style", "")})}
        clips_path.write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✓ {v['id']:18s} {len(takes)} 条 合成 {time.time() - t0:4.1f}s")
    ref_id = arg("--ref")
    profs, metrics = {}, []
    n = len([c for c in text if not c.isspace() and c not in "，。！？；：、,.!?;:“”「」"])
    for v in spec["voices"]:
        for i in take_ids(v):
            wav, mp3 = out / f"{i}.wav", out / f"{i}.mp3"
            if not mp3.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af", "loudnorm=I=-16:TP=-1.5", "-ar", "44100", "-b:a", "128k", str(mp3)], check=True)
            x = pcm(wav)
            f0 = f0_track(x)
            dur = len(x) / 16000
            profs[i] = mel_profile(x)
            metrics.append({"id": i, "name": v.get("name", v["id"]), "dur": round(dur, 2), "cps": round(n / dur, 2),
                            "f0": int(np.median(f0)), "gender": "女声" if np.median(f0) > 165 else "男声",
                            "range_st": round(float(np.std(12 * np.log2(f0 / np.median(f0)))), 2)})
    if ref_id:
        r = profs[ref_id]
        for m in metrics:
            p = profs[m["id"]]
            m["sim_to_ref"] = round(float(np.dot(p, r) / (np.linalg.norm(p) * np.linalg.norm(r))), 3)
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in metrics:
        print(f"{m['id']:18s} {m['gender']} 基频 {m['f0']:3d}Hz  起伏 {m['range_st']:.2f} 半音  {m['cps']:.2f} 字/秒" + (f"  与参照相似 {m['sim_to_ref']:.3f}" if ref_id else ""))
    if any(c.get("design") for c in clips.values()):
        print(f"挑中一条后：python3 {Path(__file__).name} {sys.argv[1]} {sys.argv[2]} --save <试听id> --name <音色名>")


if __name__ == "__main__":
    main()
