# T1-auto 尝试：SuperTux（2026-11-11）

## 结论

**失败，不记为 T1-auto。**

- attach、键盘激活、菜单 OCR、按键探针均正常；
- 但自动 probe 后进入的是 **暂停/关卡欢迎页**，不是可操作 gameplay；
- 修正 off 判定后：`gameplay_observed` 不再接受暂停页，`first_action=null`，T1 checklist 失败；
- 未生成 `origin=auto` pack；coverage 不增加。

## 观察

1. SuperTux 主菜单是中文（开始游戏/贡献的关卡/扩展/选项/退出）；
2. 自动点击 canvas 中心可能点到菜单项，进入关卡开场；
3. 开场/暂停页 OCR 只有“欢迎来到南极洲”等标题，没有稳定 gameplay HUD；
4. 探针 ENTER 可能只是打开暂停菜单，不是真正进入游戏；
5. 方向键探针没有产生可确认的移动作，故不能把 ENTER 当 first_action。

## 已修的通用问题

- `menu_options` 现在忽略长描述行，避免把 “Play ...” 说明误判为菜单；
- 新增中文菜单词（开始游戏/继续/选项/退出/重新开始/返回）；
- T1 支持 `direct_start` 与 `menu_first` 两种入口；
- `gameplay_observed` 排除暂停/继续/退出世界页面；
- 首个动作不再用 confirm 兜底，除非有分数证据。

## 结论边界

SuperTux 不是不能接，而是**需要多阶段导航**：

- 主菜单 → 开始游戏/存档；
- 世界地图 → 关卡入口；
- 开场剧情 → gameplay；
- 暂停/欢迎页识别。

当前 `auto_onboard` 只做“单阶段菜单→gameplay”，不足以稳定处理 SuperTux。  
下一款 T1-auto 应优先选“单阶段/无长过场”的游戏；SuperTux 需要先做多阶段导航或人工辅助，不能算自动 onboarding。
