# presets（自备）

开源版不带作者本人的声音样本和讲解小人形象。需要时自己放：

- 音色不放在这里：音色存在 BreezeCast 里。用 `scripts/voice_audition.py <voices.json> <试听目录>` 试听，挑中后加 `--save <take id> --name <音色名>` 存成 BreezeCast 音色；或在 BreezeCast 里克隆你本人（或已获授权）的声音。narration.json 的 `voice.voice` 写音色名即可引用。
- `presenter/*.png` + `presenter/images.presenter.json`：sketch 风格的讲解小人（10 个动作 × 8 帧）。cine 引擎（知识大赏用的）不需要。
