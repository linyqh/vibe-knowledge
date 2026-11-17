# 更新记录

## 2026-11-17 · 配音换成 BreezeCast 设计音色

- **配音引擎**：从云端 TTS 换成本机 BreezeCast（BreezeTTS 2）。新增 `tts_breeze.py`（同样的 audio/、narration.wav、timings.json、qa.json 输出，同样的逐拍缓存；逐字对齐改用本机 Murmur 的逐字时间戳）；narration.json 的 voice 块改成 `{"engine": "breeze", "voice": "AI博主沉稳男声", "style": …}`，`style` 作为语气说明（Voice Direction）发给 BreezeCast，需和旁白同语言。
- **设计音色**：默认旁白是 BreezeCast 设计出来的 AI 声音「AI博主沉稳男声」，描述见 `assets/voice/default-voice.json`。第一次用时 `voice_audition.py` 按描述出几条候选，听完选一条，`--save <take id> --name AI博主沉稳男声` 存成 BreezeCast 音色，之后每拍都是同一个人。要用自己的声音：先在 BreezeCast 里克隆，再 `new_film.py --voice 名字`。
- **回读校验**：每拍一次 Murmur（Qwen3-ASR，127.0.0.1:7895，无需密钥）转写同时给出逐字时间戳和回读文本，仍报回读相似度和 ⚠ 可疑读数。Murmur 看不到原文，专名、同音字（它 / 他）仍可能不同，回读 <95% 或 ⚠ 时再听一遍。
- **移除**：仓库不再附带任何配音音频（默认音色参照录音、试听音频），README「听一听」只留默认 BGM。
- **不再需要任何密钥**：本机运行、0 费用，没有限流问题。BreezeCast 在局域网另一台 Mac 上时用 `BREEZECAST_URL`。
- **BGM 换曲来源固定为两种**：用户要求给单期换曲时，只能是自备音频文件或本机 Songhearth 生成；Renoise Lyria、曲库、cine bed.py 不再作为 BGM 来源。新增 `tools/swap_bgm.py`（`--file` / `--songhearth`，输出 `assets/audio/bgm_user.wav` + `bgm_user.json`）；`bgm_force.py` 只认文件名是 `bgm_user.wav` 且带 `bgm: true` + 非空 `user_request` 的音乐，其余忽略、照用 vibe-bgm。
- **配音写法**（14-pitfalls.md）：数字、年份、缩写按口语写；一拍 < 约 300 字；中文方括号是人声事件；语气说明与旁白同语言。

## 2026-10-28（下午）· BGM 强制

- BGM 音量：说话时比人声低 10 dB（先定 14 dB，用户要求「高一点」改为 10）。唯一换曲口子：`bgm: true, user_request: "用户原话"`。
- 每条视频都必须有 vibe-bgm：新增 tools/bgm_force.py，钩进 finish.py。没放就自动补；其他整段配乐停用；音量按人声校准；写 build/bgm.json。
- new_film.py 建工作区时自动打钩子；qa.py 新增 BGM 检测（跟原曲开头做相关），没有就报 ⚠⚠。

## 2026-10-28 · 第 04 期 B 版《没有冰箱》沉淀

- **时长由用户定**：新增 references/13-duration.md 和 tools/duration.py。五项复杂度打分（概念数、前置知识、因果链、证据密度、分歧 / 反转），分四档（速览 / 精讲 / 标准 / 深挖），每档写清字数、拍数、细腻度、能讲到什么、要砍掉什么；推荐档排第一；用户选的档跟复杂度差两级以上会提醒。确认 1 加上「时长」这一问。
- **封面接成开头帧**：新增 tools/cover_first.py（默认停 0.5 秒，--hold 可调；带限幅，防 AAC 峰值超标）。05-publish.md 改成「封面直接做成片的开头帧」。
- **质检报冻结**：qa.py 会报 >3 秒的静止画面，>10 秒判定为录制出事。
- **know.js 新组件**：`stamp`（印章）、`cutaway`（线稿剖面图，用来替代画不准的 AI 器物图）、`tokens`（一排方块，可化掉）。
- **渲染队列安全**：queue.txt 只能追加；已有 queue.sh 在跑就不再起第二个（SKILL.md 常用命令已改）。
- **踩坑清单**：新增 references/14-pitfalls.md，按生成、配音、编排、渲染、交付五个环节整理。
