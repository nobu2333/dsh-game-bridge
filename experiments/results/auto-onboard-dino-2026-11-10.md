# T1-auto 证据：Dinosaur Game（2026-11-10）

## 结论

**T1-auto 通过**：

- 未人工填写键位、未手写 pack；
- 自动探测推断 `confirm=SPACE`、`jump=SPACE/UP`、首个有效动作 `UP`；
- `time_to_control_s = 33.961`（<5 分钟）；
- `interventions = 0`（keymap/pack 层面）；
- T1 checklist：menu/start screen、confirm、gameplay、first action 全部通过；
- 生成 pack：`experiments/games/packs/web.dino.auto.t1.json`（`origin=auto`）。

## 环境与干预边界

- 目标：Chrome 在线 Dino 页面（单机、无反作弊、键盘可玩）；
- **游戏窗口由人手动启动**，但键位/pack 未人工标注；
- 页面有广告/Close 覆盖层：onboarding 通过 OCR 发现并自动点击关闭；
- 浏览器/嵌入式页面需要先点击 canvas 才能收到键盘，onboarding 已自动点击。

因此这证明的是 **T1-auto 的键位/pack 与首个动作推断**，不是“应用启动/窗口管理也完全自动”。

## 自动流程

1. attach + 激活窗口；
2. 点击 canvas 焦点区域；
3. OCR 识别起始提示（Press Space）；
4. 探针只探测 confirm 候选键，`SPACE` 帧差/OCR 证据最好；
5. 按 `SPACE` 后，分数/画面变化 → `gameplay_observed`；
6. 在 gameplay 探测方向键，`UP` 产生有效变化 → `first_action`；
7. 生成 pack（controls/recipes/probe evidence），跑 T1 checklist；
8. 写入 `origin=auto`、`interventions=0`。

## 产物

- pack：`experiments/games/packs/web.dino.auto.t1.json`
- 本报告
- 本地原始探针报告：`tmp/auto-dino5.json`（不入库）
- coverage：`t1_total=5, t1_auto=1, t1_assisted=4, auto_target_met=true`

## 下一步

- 把同样的 auto onboarding 跑在 **第二款** 不同类型游戏上，验证泛化；
- 增加 `T1-auto` 的证据字段（探针完整记录）；
- 对“需要点击 canvas / 关闭广告”的网页游戏，把这套处理写进通用 onboarding，而不是每游戏手写；
- 不再手写新 pack 来冒充 T1-auto。
