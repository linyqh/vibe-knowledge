"""本机 Songhearth HTTP API 的最小客户端（swap_bgm.py 换曲、gen_sfx.py 音效共用）。
地址和 token 从 Songhearth 写的 api.json 读；App 没开就报错退出。"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SH_DISCOVERY = Path.home() / "Library/Application Support/com.songhearth.app/api.json"


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


def license_of(model):
    """模型详情里的许可证，统一成 {name, commercial: yes|no|conditional}。"""
    lic = model.get("license")
    return lic if isinstance(lic, dict) else {"name": lic, "commercial": model.get("commercial")}


def run(body, label):
    """提交一个生成任务并等到结束；成功返回 Generation（多一个 wall_s），失败直接退出。"""
    g = sh_call("POST", "/api/v1/generations", body)
    t0 = time.time()
    while g["status"] in ("queued", "running"):
        print(f"  Songhearth {label} {g.get('stage') or g['status']} {g.get('progress', 0):.0%}（{time.time() - t0:.0f}s）", file=sys.stderr)
        g = sh_call("GET", f"/api/v1/generations/{g['id']}/wait?timeout=600", timeout=660)
    if g["status"] != "succeeded":
        sys.exit(f"Songhearth {label} 生成失败（{g['status']}）：{g.get('error')}")
    g["wall_s"] = round(time.time() - t0, 1)
    return g


def audio(gen_id):
    """生成结果的 WAV 字节。"""
    return sh_call("GET", f"/api/v1/generations/{gen_id}/audio", timeout=600, raw=True)
