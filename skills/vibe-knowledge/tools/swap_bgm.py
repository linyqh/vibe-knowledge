#!/usr/bin/env python3
"""给某一期换 BGM（只在用户明确要求换曲时用）。来源只有两个：用户自己给的音频文件，或本机 Songhearth 生成。
用法：
  python3 swap_bgm.py <期目录> --request "用户原话" --file ~/Music/夏日.mp3
  python3 swap_bgm.py <期目录> --request "用户原话" --songhearth "lofi hip hop, warm rhodes piano, soft drums, 90 BPM, no vocals" [--model ace-step-1.5-turbo] [--seed 1234]
  可选 --tail 3：片长 = build/timings.json 的 total + tail（和 fit_bgm.py 一样，先配完音再换曲）。
做法：
  --file：转成 48 kHz 立体声，裁到片长，末尾 1.8 秒淡出；曲子比片子短就照实报出来（没有节拍数据，不循环）。
  --songhearth：本机 Songhearth 生成纯音乐，时长正好等于片长。默认 ace-step-1.5-turbo（MIT，可商用）；
    提示词用英文逗号分隔的标签（风格、乐器、情绪、BPM）。换别的模型时会打印它的许可证，不可商用的模型直接拒绝。
输出：<期目录>/assets/audio/bgm_user.wav + bgm_user.json（来源、提示词、模型、seed、许可证、用户原话），并打印 film.js 里要写的那一行。
bgm_force.py 只认文件名为 bgm_user.wav、并写了 bgm: true + user_request 的条目，别的来源一律不认。"""
import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SH_DISCOVERY = Path.home() / "Library/Application Support/com.songhearth.app/api.json"
DEFAULT_MODEL = "ace-step-1.5-turbo"
FADE_OUT = 1.8


def sh_call(method, path, body=None, timeout=60, raw=False):
    cfg = json.loads(SH_DISCOVERY.read_text()) if SH_DISCOVERY.exists() else {}
    url = (cfg.get("url") or "http://127.0.0.1:17865").rstrip("/")
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else {})}
    req = urllib.request.Request(url + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return data if raw else json.loads(data)
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except ValueError:
            err = {}
        sys.exit(f"Songhearth {path}：[{err.get('code', e.code)}] {err.get('message', e.reason)}")
    except urllib.error.URLError as e:
        sys.exit(f"连不上 Songhearth（{url}）：{e.reason}。先打开 Songhearth")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def fit(src, out, length):
    """转 48 kHz 立体声、裁到片长、末尾淡出；返回原曲时长。"""
    dur = probe(src)
    end = min(dur, length)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-t", f"{end:.3f}", "-af", f"afade=t=out:st={max(0, end - FADE_OUT):.3f}:d={FADE_OUT}",
                    "-ac", "2", "-ar", "48000", str(out)], check=True)
    return dur


def songhearth(prompt, model, length, seed, out):
    h = sh_call("GET", "/api/v1/health", timeout=10)
    if not (h.get("engine") or {}).get("ready"):
        sys.exit("Songhearth 引擎没就绪：在 Songhearth → 设置 → 安装引擎")
    m = sh_call("GET", f"/api/v1/models/{model}")
    if model not in h.get("installedModels", []):
        sys.exit(f"Songhearth 没装 {model}（{m.get('sizeGB')} GB）：先在 Songhearth 里下载，或换 --model（已装：{'、'.join(h.get('installedModels', []))}）")
    lic = m.get("license") if isinstance(m.get("license"), dict) else {"name": m.get("license"), "commercial": m.get("commercial")}
    if lic.get("commercial") == "no":
        sys.exit(f"{model} 的许可证（{lic.get('name')}）不可商用，成片要发布，换 --model {DEFAULT_MODEL}")
    if not m.get("instrumental"):
        sys.exit(f"{model} 不能生成纯音乐，换 --model {DEFAULT_MODEL}")
    rng = m.get("duration") or {}
    secs = math.ceil(length)
    if rng.get("max") and secs > rng["max"]:
        sys.exit(f"片长 {secs}s 超过 {model} 的上限 {rng['max']}s，换模型")
    if rng.get("mode") != "exact":
        print(f"⚠ {model} 的时长是上限不是精确值，生成后会按片长裁剪", file=sys.stderr)
    if lic.get("commercial") != "yes":
        print(f"⚠ {model} 许可证：{lic.get('name')}（商用：{lic.get('commercial')}），发布前确认条款", file=sys.stderr)
    body = {"model": model, "kind": "music", "prompt": prompt, "instrumental": True, "duration": secs, "title": f"vibe-knowledge BGM {secs}s"}
    if seed is not None:
        body["seed"] = seed
    g = sh_call("POST", "/api/v1/generations", body)
    t0 = time.time()
    while g["status"] in ("queued", "running"):
        print(f"  Songhearth 生成中 {g.get('stage') or g['status']} {g.get('progress', 0):.0%}（{time.time() - t0:.0f}s）", file=sys.stderr)
        g = sh_call("GET", f"/api/v1/generations/{g['id']}/wait?timeout=600", timeout=660)
    if g["status"] != "succeeded":
        sys.exit(f"Songhearth 生成失败（{g['status']}）：{g.get('error')}")
    out.write_bytes(sh_call("GET", f"/api/v1/generations/{g['id']}/audio", timeout=600, raw=True))
    return {"model": model, "license": lic.get("name"), "commercial": lic.get("commercial"), "prompt": prompt, "seed": g.get("seed"),
            "generation_id": g["id"], "output_path": g.get("outputPath"), "wall_s": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lesson")
    ap.add_argument("--request", required=True, help="用户要求换曲的原话")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="用户提供的音频文件")
    src.add_argument("--songhearth", metavar="PROMPT", help="Songhearth 生成提示词（英文标签）")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--tail", type=float, default=3.0)
    a = ap.parse_args()
    if not a.request.strip():
        sys.exit("--request 要写用户的原话")

    L = Path(a.lesson).expanduser().resolve()
    tj = L / "build/timings.json"
    if not tj.exists():
        sys.exit(f"没有 {tj}：先配音，片长定了再换曲")
    length = json.loads(tj.read_text(encoding="utf-8"))["total"] + a.tail
    out = L / "assets/audio/bgm_user.wav"
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        if a.file:
            f = Path(a.file).expanduser().resolve()
            if not f.exists():
                sys.exit(f"找不到音频文件：{f}")
            info = {"source": "file", "file": str(f)}
            raw = f
        else:
            raw = Path(td) / "songhearth.wav"
            info = {"source": "songhearth", **songhearth(a.songhearth, a.model, length, a.seed, raw)}
        dur = fit(raw, out, length)
    info.update(request=a.request, length_s=round(length, 3), source_duration_s=round(dur, 3))
    out.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"✓ BGM：{out}（{'用户文件 ' + Path(info['file']).name if a.file else 'Songhearth ' + a.model + ' seed ' + str(info['seed'])}，片长 {length:.1f}s）")
    if dur < length - 0.5:
        print(f"⚠ 曲子只有 {dur:.1f}s，比片子短 {length - dur:.1f}s，后面没有 BGM：换一首更长的，或用 --songhearth 按片长生成")
    req = a.request.replace("\\", "\\\\").replace('"', '\\"')
    print("film.js 里把默认 bgm.wav 那条换成：")
    print(f'  music.push({{ src: P("audio/bgm_user.wav"), from: 0, at: 0, dur: END + TAIL, fade_in: 0.3, fade_out: {FADE_OUT}, bgm: true, user_request: "{req}" }});')


if __name__ == "__main__":
    main()
