#!/usr/bin/env python3
"""新建一期知识短片（建在 ai-teardown 的 cine 引擎上）。

用法：
  python3 ~/.claude/skills/vibe-knowledge/tools/new_film.py <期号> --template A --title "本福特定律" [--ws ~/Desktop/vibe-knowledge] [--series vk]
         [--voice <BreezeCast 音色名>] [--ratio 16:9]

做的事：
1. 工作区 / 系列不存在就调用 ai-teardown 的 new_series.py --style cine 建好（引擎、字体、渲染工具）。
2. 把 kit/know.js 装进 <系列>/cine/engine/，给 cine/tools/record.py、stills.py 打补丁：每次 seek 之后 await window.__vk.wait()（等配图、视频帧解码完再截图）。
3. narration.json 的 voice.voice 写成 BreezeCast 音色名（默认「AI博主沉稳男声」：BreezeCast 设计的 AI 声音，不是真人；第一次用先按 assets/voice/default-voice.json 试听、保存）。
4. lessons/<期号>/：narration.json（母版旁白骨架）、film.js（画面骨架）、facts.md（事实清单）、assets.json（增强档资产清单：图 / 视频 / 音效）、assets/{img,clips,audio}/。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
AT = Path.home() / ".claude/skills/ai-teardown"
DEFAULT_VOICE = os.environ.get("VK_VOICE") or "AI博主沉稳男声"   # BreezeCast 里保存的音色名；想用自己的声音就先在 BreezeCast 克隆，再传 --voice 或设 VK_VOICE

SEEK = 'pg.evaluate("(t) => window.__film.seek(t)", t)'
PATCHED = SEEK + '; pg.evaluate("() => window.__vk ? window.__vk.wait() : null")'


def patch_tools(sd: Path):
    for name in ("record.py", "stills.py"):
        p = sd / "cine/tools" / name
        s = p.read_text(encoding="utf-8")
        if "__vk" in s:
            continue
        if SEEK not in s:
            sys.exit(f"{p} 里找不到 seek 调用，cine 引擎改过了，补丁要重写")
        p.write_text(s.replace(SEEK, PATCHED), encoding="utf-8")
        print(f"✓ 补丁：{p.relative_to(sd)}")


FIN_OLD = '"-i", str(m["src"]),'
FIN_NEW = '"-i", str(m["src"] if Path(m["src"]).is_absolute() else ROOT / m["src"]),'


def patch_finish(sd: Path):
    p = sd / "cine/tools/finish.py"
    s = p.read_text(encoding="utf-8")
    if FIN_NEW in s:
        return
    if FIN_OLD not in s:
        sys.exit(f"{p} 里找不到 music src 的写法，cine 引擎改过了，补丁要重写")
    p.write_text(s.replace(FIN_OLD, FIN_NEW), encoding="utf-8")
    print(f"✓ 补丁：{p.relative_to(sd)}（music 的 src 可写相对系列目录的路径）")


def patch_bgm(sd: Path):
    # 知识大赏强制 BGM（用户规定）：finish.py 混音时没放 vibe-bgm 就自动补，音量按人声校准
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "bgm_force.py"), "--patch", str(sd)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--template", required=True, choices=list("ABCDEF"))
    ap.add_argument("--title", required=True)
    ap.add_argument("--ws", default=str(Path.home() / "Desktop/vibe-knowledge"))
    ap.add_argument("--series", default="vk")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    a = ap.parse_args()

    ws = Path(a.ws).expanduser().resolve()
    sd = ws / "examples" / a.series
    if not (sd / "cine/engine/core.js").exists():
        subprocess.run([sys.executable, str(AT / "engine/scripts/new_series.py"), str(ws), a.series, "--style", "cine", "--title", "Vibe知识大赏"], check=True)
        shutil.copytree(AT / "templates/series-cine/tools", sd / "tools", dirs_exist_ok=True)
    shutil.copy(SKILL / "kit/know.js", sd / "cine/engine/know.js")
    patch_tools(sd)
    patch_finish(sd)
    sys.path.insert(0, str(SKILL / "tools")); import patch_earshot; patch_earshot.patch(sd)   # earshot 代码音效（必须在 BGM 钩子之前：BGM 钩子锚在 earshot 改过的配乐循环上）
    patch_bgm(sd)

    L = sd / "lessons" / a.id
    if L.exists():
        sys.exit(f"这一期已存在：{L}")
    for d in ("assets/img", "assets/clips", "assets/audio", "build", "stills"):
        (L / d).mkdir(parents=True)
    T = SKILL / "templates"
    narr = json.loads((T / f"narration/{a.template}.json").read_text(encoding="utf-8"))
    narr["voice"]["voice"] = a.voice
    (L / "narration.json").write_text(json.dumps(narr, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    film = (T / "film.skeleton.js").read_text(encoding="utf-8").replace("__TITLE__", a.title).replace("__ID__", a.id).replace("__TPL__", a.template)
    (L / "film.js").write_text(film, encoding="utf-8")
    shutil.copy(T / "facts.md", L / "facts.md")
    shutil.copy(T / "assets.json", L / "assets.json")
    print(f"✓ 新一期：{L}\n  母版 {a.template} · {a.title} · 音色 {a.voice}\n  下一步：写 facts.md → narration.json → assets.json（报价确认）→ 配音 → film.js")


if __name__ == "__main__":
    main()
