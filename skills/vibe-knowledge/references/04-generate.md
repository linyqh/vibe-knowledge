# 04 · 增强层生成：图、视频、音效

| 资产 | 用什么 | 花不花钱 |
|---|---|---|
| 配图 | omp 内置工具 `generate_image`（`xd://generate_image`） | 花钱：取决于 omp 配置的图像模型和提供方 |
| 动态镜头 | omp 内置工具 `xai_generate_video`（`xd://xai_generate_video`，xAI Grok Imagine） | 花钱：按输出秒数计费 |
| 音效 | 本机 Songhearth，`tools/gen_sfx.py` 按 assets.json 批量生成 | 0 费用、无需密钥 |
| 配乐 | 不在增强层：默认 vibe-bgm；用户要求换曲时自备文件或本机 Songhearth（`tools/swap_bgm.py`），见 SKILL.md「BGM」 | |

**花钱的硬规矩**：把整期的 assets.json 列成一张表（图：张数和提示词；视频：模型、分辨率、秒数、首帧、提示词、秒数 × 单价小计；音效：条数和提示词）发给用户，**等用户在对话里明确说可以**才调 `generate_image` / `xai_generate_video`。宿主的工具授权弹窗不算确认；之前说过「直接生成」也不算。改了任何提示词、模型、秒数、数量就要重新报价确认。音效本机生成不花钱，跟着确认 2 一起列出即可。

## 开工前检查（基础档不需要；做增强档时才查）

- **生图**：当前会话的工具列表里有 `generate_image`（能读到 `xd://generate_image`）。用哪个模型由 omp 的图像模型设置决定（本机 2026-11-17 实测：`gpt-image-2.5-sunburst`，16:9 出 1672×941 PNG）；要指定模型就在调用里写 `model`。
- **视频**：工具列表里有 `xai_generate_video`；omp 里要配好 xAI 的 key，没配会直接报错，让用户在 omp 设置里补上。
- **音效**：`python3 ~/.claude/skills/vibe-knowledge/tools/gen_sfx.py` 第一步会查 Songhearth（App 已打开、引擎就绪、装了可商用的音效模型），缺什么它会直接说。推荐装 `moss-soundeffect-v2`（Apache-2.0，中英文提示词，≤30 秒，需要比 0.9.4 新的引擎）；`stable-audio-3-small-sfx`（Stability 社区许可，年收入 < 100 万美元可商用，英文提示词，≤60 秒）也能用。`controlfoley` 不可商用，脚本会拒绝。

## 单价（2026-11-17；按分辨率分档，以 https://docs.x.ai/developers/models 为准）

xAI 模型页首页只列每个模型的最低价（480p），**720p / 1080p 更贵**。报价一律按实际要出的分辨率算。实测：`grok-imagine-video` 720p 8 秒图生视频扣费 $0.562（$0.07/秒 × 8 + 首帧图 $0.002）。

| 资产 | 模型 | 单价 | 用在 |
|---|---|---|---|
| 场景 / 氛围 / 示意 / 地图底图 | `generate_image`（omp 配置的模型） | 看提供方 | 所有配图；地图、器物剖面也走它，提示词写清结构 |
| 主视觉动态镜头 | `grok-imagine-video`（默认，最高 720p） | 480p $0.05/秒、**720p $0.07/秒**（实测 8 秒 720p = $0.562） | 大多数动态镜头（首帧 = 已生成的配图） |
| 高难动态镜头 / 1080p | `grok-imagine-video-1.5`（图生视频可出原生 1080p） | 480p $0.08/秒、720p $0.14/秒、1080p $0.25/秒（官方文档标价，未实测） | 反转 / 高潮那一两个镜头 |
| 便宜试镜头 | `grok-imagine-video-1.5-lite` | 480p $0.02/秒、720p $0.03/秒（官方文档标价，未实测） | 先试运动方向，满意再用正式模型重出 |
| 图生视频的首帧图 | 以上全部 | 每张 $0.002 | — |
| 单个音效 | Songhearth `gen_sfx.py` | 0 | 钟声、翻书、风、人群 |

**一期预算**：按 08-tiers.md 的增强等级。只增强代码做不好的镜头，其余照样代码做。

## 流程

1. **写 assets.json**：每一项写清 `use`（哪一拍、做什么用）、`kind`（image / video / sfx）、提示词、`file`（相对 `assets/`）。图的提示词 = `style_prefix` + 本张内容 + `no text, no letters, no watermark`。
2. **先图后视频**：动态镜头一律用已生成的配图做首帧，保证动静一致；所以分两轮报价：第一轮图（音效同时本机生成），第二轮视频（第一轮出图后用户挑图）。也可以一次把两轮都列进预览、一次确认（预览里写明第二轮的首帧取自第一轮哪张）。
3. **出图**：每张调一次 `generate_image`（`subject` / `scene` / `composition` / `lighting` / `style` 分开写，`style` 放 style_prefix；`aspect_ratio: "16:9"`）。工具返回的是临时目录里的 PNG，马上转成成片要的 JPG：
   `ffmpeg -v error -y -i <返回的.png> -vf "scale=1920:-2:flags=lanczos,unsharp=5:5:0.4" -q:v 2 $L/assets/img/a01.jpg`（1672→1920 只放大 1.15 倍，Lanczos + 轻锐化就够，见 12-style-families.md 坑 3）。assets.json 里该条 `status` 改 done。要候选就多调几次，别一次堆在一个提示词里。
4. **出音效**：`python3 ~/.claude/skills/vibe-knowledge/tools/gen_sfx.py $L`（只做 kind 为 sfx、status 为 plan / approved 的条目；`--only s01,s03` 只做几条；`--redo` 重做）。输出 48 kHz 立体声 WAV 到 `assets/<file>`，自动回写 status、模型、seed、许可证。
5. **出视频**：每个镜头调一次 `xai_generate_video`：`image` = 选中的首帧图（本地 JPG/PNG 路径）、`prompt` 只写变化、`duration`（1–15 秒，一般 8）、`resolution`（默认 720p）、`model`（不写 = `grok-imagine-video`）、`output_path` = `lessons/NN/assets/clips/v01.mp4`。图生视频时输出比例自动跟随首帧，`aspect_ratio` 不用写。**每次调用就是一次付费任务：已经返回任务号的不要重试**，失败了先报给用户、改提示词、重新报价。
6. **视频进画面**：`python3 ~/.claude/skills/vibe-knowledge/tools/clip2frames.py assets/clips/v01.mp4 assets/clips/v01 --fps 30` → 打印帧数 n → film.js 里 `vclip(s, { dir: A("clips/v01"), n })`。有信箱黑边会自动裁掉，拆完抽一帧确认首行不是黑的。视频自带生成的原声，clip2frames 另存为 `assets/clips/v01/audio.wav`，要用就加一条 music：`{ src: P("clips/v01/audio.wav"), at, dur, gain: -20 }`。
7. 不满意的单张 / 单个镜头：只重做那一个（视频要新报价、新确认），别整批重来。

## 提示词写法

### 配图（generate_image）
短句视觉描述，不写需求文档，按字段拆开：
- `subject`：主体；`scene`：环境；`lighting`：光线；`composition`：`wide shot / low angle / negative space on the right for text`；`style`：本期 style_prefix。
- 结尾带 `no text, no letters, no watermark`：地名、数字、标题全部由代码叠加（spread / keyword），不让模型写字。
- 给关键词留位置：写明 `negative space on the left/right/top`。
- 人物不写具体面部，写剪影 / 背影 / 远景，减少「像某个真人」的风险。
- 同一角色 / 同一场景要多张一致：后面几张把第一张作为 `input` 传进去，`subject` 里写「Image 1 is the reference for the character and setting」。
- 地图 / 示意图照样走 generate_image，结构写清楚：
```
subject: antique paper map of Tang dynasty China, Yellow River and major prefectures as subtle ink lines
composition: 16:9, map centered, wide margins, no labels
style: <style_prefix>, no text, no letters, no numbers, no legend, no watermark
```
- 最宽只有 16:9：长卷这类超宽画幅分 3 段 16:9 生成（第 2、3 段把上一段作为 `input`，写「continue this handscroll scene to the left, same style, lighting and silk texture」），再用 `tools/stitch_scroll.py` 从右往左羽化拼接（见 styles/scroll/STYLE.md）。

### 动态镜头（xai_generate_video）
首帧模式，只写**变化**，不重复描述静态画面：
`[主体的动作 / 环境的变化], [一个镜头运动：slow push-in / slow dolly left], [光线变化], [环境声：wind, distant crowd], no text, no subtitles, no dialogue`
- 8 秒足够，一个镜头一个动作；需要更复杂的运动或 1080p 用 `grok-imagine-video-1.5`。
- 生成的原声可当环境声；不要对白（模型会对口型说话，写明 no dialogue）。

### 音效（Songhearth）
物理描述 + 真实长度，写在 assets.json 的 `prompt` / `duration`：`a single temple bell struck once in a cold stone courtyard, long natural decay` · 3 秒。一条一个音效。`stable-audio-3-small-sfx` 只认英文提示词；`moss-soundeffect-v2` 中英文都行。

## 实测坑

- 统一画风前缀会压过单张描述：时代不同的那张（如宋代书房）要换前缀，否则会被画成战国城楼。
- 首帧视频不一定照提示词演（第 01 期有一条没「关门」，而是走进来一个斗篷人）：先看片再决定用不用，别默认能用。
- generate_image 返回的 PNG 在临时目录，会被清掉：拿到就转存进 `assets/img/`。

## 安全

- 不生成在世真人的脸、不模仿品牌 logo；历史人物写「人物造型为示意」。
- 生成画面一律角标「AI 示意图 / AI 生成画面」（plate、vclip 默认带）。
- 不把用户的私人素材传给生图或视频模型（`input` / `image`），除非用户明确要用。
