# B 轨 SuperTux 冷启动烟测：部分完成（2026-11-06）

## 目标

零引擎改动验证 SuperTux（Windows x64 portable）的 attach、抓屏/OCR、键盘控制、进入 gameplay、`game_id=supertux` 的 LevelMemory 加载/卸载。

## 已验证

- 启动：`F:\SuperTux-portable\bin\supertux2.exe`，窗口标题 `SuperTux v0.7.0`，窗口 1280×831；
- **attach 成功**：`session.attach({"window": "SuperTux v0.7.0"})`，foreground/截图正常；
- **抓屏/OCR 成功**：
  - 首启“允许联网？”弹窗可 OCR；
  - 主菜单 OCR（开始游戏/贡献的关卡/扩展/选项）；
  - 暂停菜单 OCR（继续/选项/退出世界）；
  - 世界地图/关卡名“与恋人的午餐”可 OCR；
- **鼠标注入可用**：点掉“否”、点“开始游戏”、点“贡献的关卡”有效；
- **键盘注入可用前提**：SuperTux 必须被 `AppActivate` 真正激活；激活后 ESC 能打开暂停菜单；
- 已修通用输入：`SendInput` 现在同时填 `wVk + wScan`（`MapVirtualKeyW`），兼容 SDL 游戏；
- 已加通用 profile：`profiles/supertux.json`（方向/Space/Ctrl/Shift/Enter，player.track=false）。

## 未完成

- **没有进入 gameplay**：当前停留在世界地图；
- 从地图节点按 Space 触发的是剧情/过场，ESC 跳过会返回地图，未进入关卡；
- 因此没有 `time_to_controls` 的 gameplay 里程碑、没有首次有效移动动作、没有 `traces/` 和 health 轨迹；
- 没有生成 LevelMemory 加载/卸载证据。

## 结论

B 轨当前阻塞在 **SuperTux 世界地图→关卡入口** 这一交互步骤，不是引擎 attach/OCR/输入本身。需要人工把角色带进一个可操作关卡，之后即可继续完成剩余验收项。
