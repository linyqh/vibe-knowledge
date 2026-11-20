#!/usr/bin/env python3
"""按 assets.json 用本机 Songhearth 生成音效（增强档；0 费用、无需密钥）。
用法：
  python3 gen_sfx.py <期目录> [--only s01,s03] [--model auto] [--redo]
做法：
  - 取 assets.json 里 kind 为 "sfx"、status 为 plan / approved 的条目（--redo 连 done 的也重做；--only 只做列出的 id）。
    每条要有 prompt（物理描述：声源、动作、材质、空间、距离；一条一个声音）、duration（秒）、file（相对 assets/）。
  - --model auto：在「已安装 + 引擎支持 + 可商用」的音效模型里按 moss-soundeffect-v2 → stable-audio-3-small-sfx 的顺序挑；
    指定模型时同样检查。许可证不可商用的（如 controlfoley）直接拒绝，带条件的打印提醒。
  - 输出转成 48 kHz 立体声 WAV 写到 assets/<file>；条目回写 status: done、model、seed、generation_id、license。
film.js 里：music.push({ src: P("audio/sfx_bell.wav"), from: 0, at: T("B07.reveal"), dur: 3, gain: -8 });"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from songhearth_api import audio, license_of, run, sh_call

PREFERRED = ["moss-soundeffect-v2", "stable-audio-3-small-sfx"]  # 48 kHz、可商用；midashenglm-gen 只有 16 kHz 草稿质量，不自动选


def usable(model_id, health, families):
    """返回 (模型详情, 不能用的原因或 None)。"""
    m = sh_call("GET", f"/api/v1/models/{model_id}")
    if m.get("kind") != "sfx":
        return m, f"{model_id} 不是音效模型"
    if model_id not in health.get("installedModels", []):
        return m, f"{model_id} 没装（在 Songhearth 里下载）"
    if m.get("family") not in families:
        return m, f"{model_id} 需要更新的 Songhearth 引擎（当前 {(health.get('engine') or {}).get('version')}）"
    if license_of(m).get("commercial") == "no":
        return m, f"{model_id} 的许可证（{license_of(m).get('name')}）不可商用，成片要发布"
    return m, None


def pick(want):
    h = sh_call("GET", "/api/v1/health", timeout=10)
    if not (h.get("engine") or {}).get("ready"):
        sys.exit("Songhearth 引擎没就绪：在 Songhearth → 设置 → 安装引擎")
    families = set(sh_call("GET", "/api/v1/engine").get("families", []))
    reasons = []
    for mid in (PREFERRED if want == "auto" else [want]):
        m, why = usable(mid, h, families)
        if not why:
            lic = license_of(m)
            if lic.get("commercial") != "yes":
                print(f"⚠ {mid} 许可证：{lic.get('name')}（{lic.get('note') or '商用有条件'}），发布前确认条款", file=sys.stderr)
            return mid, m
        reasons.append(why)
    sys.exit("没有可用的音效模型：" + "；".join(reasons) + "。推荐在 Songhearth 里安装 moss-soundeffect-v2（Apache-2.0）或 stable-audio-3-small-sfx")


def save(path, data):
    """回写 assets.json：顶层字段照常缩进，items 一条一行（和模板一样好读）。"""
    head = {k: v for k, v in data.items() if k != "items"}
    lines = [f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}," for k, v in head.items()]
    items = [f"  {json.dumps(it, ensure_ascii=False)}" for it in data.get("items", [])]
    path.write_text("{\n" + "\n".join(lines) + '\n "items": [\n' + ",\n".join(items) + "\n ]\n}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lesson")
    ap.add_argument("--only", help="逗号分隔的条目 id")
    ap.add_argument("--model", default="auto")
    ap.add_argument("--redo", action="store_true", help="status 为 done 的也重做")
    a = ap.parse_args()

    L = Path(a.lesson).expanduser().resolve()
    aj = L / "assets.json"
    if not aj.exists():
        sys.exit(f"没有 {aj}：先用 new_film.py 建工作区")
    data = json.loads(aj.read_text(encoding="utf-8"))
    only = set(a.only.split(",")) if a.only else None
    todo = [it for it in data.get("items", []) if it.get("kind") == "sfx"
            and (only is None or it.get("id") in only)
            and (it.get("status") in ("plan", "approved") or (a.redo and it.get("status") == "done"))]
    if not todo:
        sys.exit("assets.json 里没有待生成的音效（kind: sfx，status: plan / approved）")
    for it in todo:
        missing = [k for k in ("prompt", "duration", "file") if not it.get(k)]
        if missing:
            sys.exit(f"{it.get('id')} 缺 {'、'.join(missing)}")

    model, m = pick(a.model)
    rng = m.get("duration") or {}
    lic = license_of(m)
    print(f"音效模型：{model}（{lic.get('name')}），共 {len(todo)} 条", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td:
        for it in todo:
            dur = round(min(max(float(it["duration"]), rng.get("min", 1.0)), rng.get("max", 30.0)), 1)
            if dur != float(it["duration"]):
                print(f"⚠ {it['id']} 时长 {it['duration']}s 超出 {model} 范围，按 {dur}s 生成", file=sys.stderr)
            body = {"model": model, "kind": "sfx", "prompt": it["prompt"], "duration": dur, "title": f"vibe-knowledge {it['id']}"}
            if it.get("seed") is not None and not a.redo:
                body["seed"] = it["seed"]
            g = run(body, it["id"])
            raw = Path(td) / f"{it['id']}.wav"
            raw.write_bytes(audio(g["id"]))
            out = L / "assets" / it["file"]
            out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ac", "2", "-ar", "48000", str(out)], check=True)
            it.update(status="done", model=model, seed=g.get("seed"), generation_id=g["id"], license=lic.get("name"))
            save(aj, data)  # 每条完成就回写，中途失败不丢已完成的
            print(f"✓ {it['id']} → assets/{it['file']}（{dur}s，seed {g.get('seed')}，{g['wall_s']}s）")


if __name__ == "__main__":
    main()
