# 状态模型（STATE）

> 本文定义**通用玩法基线**的数据形状与降级规则：WorldState、GameProfile、provider 分层、
> confidence / stale 语义、安全边界，以及 `game_state` / `game_policy` / `game_memory`
> 如何映射到它。设计理由见 [DESIGN](DESIGN.md) §2.6；键名清单见 [CONTROLS](CONTROLS.md)。
> 契约来源是 `tmp/general-state-contract.md`（Lead 所有）；实现以
> `engine/dsh_game_core/state.py`、`policy.py`、`lib/profile-store.js` 为准。
>
> 公开仓库红线：不写游戏内存偏移、不写本机路径/用户名/密钥、不提交内存转储。
> 任何游戏特有的键位、HUD 区域、颜色阈值都只能进 profile JSON（见 §3）。

## 0. 一句话

**状态 = 视觉保底 + 档案数据 + 可选 provider。** 引擎里没有「Cuphead」这种名字，只有
`hud.hp.box`、`combat.advance` 这类通用字段；视觉层在没有档案、没有内存、没有网络时
也必须能返回一个（哪怕全是 `unknown` 的）WorldState。

## 1. 分层模型

```
模型 / DSH 工具（低频：看一眼、起停策略）
        │  game_state / game_policy / game_memory
        ▼
┌──────────────────────────────────────────────────────────────┐
│ 策略层 PolicyRunner（本地 60 Hz，可选）                        │
│   hold / advance / dodge（威胁半径）/ stuck（卡住脱困）        │
└───────────────────────┬──────────────────────────────────────┘
                        │ 每拍读当帧 WorldState.entities / player / scene
┌───────────────────────▼──────────────────────────────────────┐
│ 状态层 StateProvider（按优先级合并，失败即降级）                │
│   L2  memory / API provider（可选，当前未实现）                │
│   L1  profile 视觉细化（HUD 区域 / 场景关键词 / 颜色 / 键位）   │
│   L0  视觉保底 vision（始终可用，零游戏知识）                   │
└───────────────────────┬──────────────────────────────────────┘
                        │ 帧（BGR）+ OCR 行
┌───────────────────────▼──────────────────────────────────────┐
│ 采集层：DXcam 整屏抓 + 窗口矩形裁剪 / RapidOCR                  │
└──────────────────────────────────────────────────────────────┘
```

| 层 | 数据来源 | 必需？ | 失败时 | 现状 |
|:--|:--|:--|:--|:--|
| L0 视觉保底 | 当帧画面 + OCR 行 | 是 | 返回 unknown 默认值，不抛异常 | 已实现 |
| L1 档案细化 | `GameProfile` JSON（用户本地） | 否 | 退回代码默认阈值 | 已实现 |
| L2 memory provider | 用户本地的只读适配器 / 外部状态源 | 否 | 保留视觉值，标 `stale` | **未实现（设计位）** |
| L2 API provider | 游戏/平台提供的只读 API | 否 | 同上 | **未实现（设计位）** |

四条不变量：

1. **视觉是地板**：任何游戏、任何分辨率、没有档案也能产出 WorldState 的字段结构；
   值可能是 `null` / `unknown`，但不允许整体失败。
2. **档案是数据，不是代码**：引擎按字段解释 profile，不按游戏名分支；加一个游戏 =
   加一个 JSON 文件，不改引擎。
3. **provider 是可选加速器**：它只允许覆盖自己拥有的字段；缺失时基线照常工作，
   失败时降级而不是连坐。
4. **安全闸独立于状态来源**：不管状态来自视觉还是 provider，输出通道仍先过反作弊、
   F12 夺回、真实后端审批与前台校验（§6）。

## 2. WorldState（`game_state` 返回的 JSON）

```json
{
  "schema": 1,
  "t": 1793329000.123,
  "scene": "menu",
  "confidence": 0.8,
  "player": {"x": null, "y": null, "hp": 3, "max_hp": 3, "state": "unknown"},
  "entities": [
    {"kind": "threat", "x": 0.42, "y": 0.61, "score": 0.8}
  ],
  "ui": {
    "texts": [{"text": "HP.3", "score": 0.99, "x": 0.05, "y": 0.95}],
    "prompt": "CONFIRM Z",
    "hp_text": "3"
  },
  "game": {"profile": "cuphead", "provider": "vision", "stale": false},
  "foreground": {"hwnd": 0, "title": "…", "process": "…", "left": 0, "top": 0, "width": 0, "height": 0},
  "occluded": {"available": true, "occluded_ratio": 0.0, "occluded": false, "covered_by": []}
}
```

> `foreground` 可能是 `null`；`occluded` 的形状与 `game_snapshot` 一致（`covered_by`
> 只保留遮挡比例最高的前 3 个窗口）。session 还会在返回值上追加 `backend`（当前控制
> 后端名）——这些都属于**附加字段**，消费方应容忍。

### 顶层字段

| 字段 | 类型 | 含义 |
|:--|:--|:--|
| `schema` | int | 状态版本，当前恒为 `1`；只做加法式演进 |
| `t` | number | 本帧时间戳（epoch 秒） |
| `scene` | string | `menu` / `gameplay` / `cutscene` / `dialogue` / `death` / `loading` / `unknown` |
| `confidence` | number | 整条状态可信度 0..1；`unknown` 为 `0.0` |
| `player` | object | 玩家位置与血量；未知字段为 `null` |
| `entities` | array | 归一化坐标的实体（威胁 / 弹反点），按 `score` 降序 |
| `ui` | object | OCR 语义：文本行、提示语、HP 文本 |
| `game` | object | 本条状态用了哪个 profile、哪个 provider、是否 stale |
| `foreground` / `occluded` | object / null | 前台窗口与遮挡诊断（session 填） |
| `backend` | string | 当前控制后端（`dry-run` / `vgamepad` / `keyboard`；实现附加） |

### `scene` 判定顺序

按优先级从上到下，命中即停；全程不抛异常。

| scene | 判定 |
|:--|:--|
| `death` | OCR 命中 `scene.death_keywords`（默认 `GAME OVER` / `YOU DIED` / `DEAD` / `RETRY`） |
| `menu` | OCR 命中 `scene.menu_keywords`（默认 `START` / `OPTIONS` / `EXIT` / `CONTINUE`） |
| `gameplay` | 识别出 HP（`hud.hp.box` 区域内的 OCR，或未配置 box 时的通用 HP 规则） |
| `loading` | 近黑画面（仅当场景本是 `unknown` / `dialogue` 时提升，`confidence` 0.5），或 OCR 行数在 `1..loading_max_texts` 之间（默认 1） |
| `dialogue` | 有 OCR 文本但没有 HP |
| `unknown` | 其余情况，或提取失败 |

### `player` / `entities`

| 字段 | 说明 |
|:--|:--|
| `player.x` / `.y` | 归一化坐标；视觉层通常拿不到，为 `null`（provider 才能填） |
| `player.hp` / `.max_hp` | HP / OCR 结果；未知为 `null`（`max_hp` 可由 profile/HUD 推断） |
| `player.state` | `"unknown"`，预留 |
| `entities[].kind` | 当前实现只有 `parry`（弹反点）与 `threat`（移动威胁）；`enemy` 是保留值 |
| `entities[].x` / `.y` | 归一化 0..1，相对当帧；以帧左上角为原点、右下角为 `(1, 1)` |
| `entities[].score` | 0..1，越高越可信；`entities` 按它降序，最多保留 12 个（威胁最多 10 个） |

`parry` 用颜色阈值检测（profile `colors.parry`：`r_min` / `b_min` / `rb_minus_g_min` /
`min_pixels`）；`threat` 用廉价帧差 + 背景百分位 + 网格聚合，跳过自身区域。
两者都在**无 OCR 的 60 Hz 路径**上（契约目标 <3 ms @962×567，性能预算由引擎单测守住），
绝不被 `game_state` 的 OCR 成本拖慢——`game_policy` 只吃这条路径。

### `ui` 与 `game`

| 字段 | 说明 |
|:--|:--|
| `ui.texts[]` | `{text, score, x, y}`，`x`/`y` 是归一化位置（取该 OCR 行中心），坐标不可推导时为 `null`；最多保留 64 行 |
| `ui.prompt` | 从 OCR 里挑出的短提示（如 `CONFIRM Z`），可能为 `null`；可用 profile 的 `prompt_keywords` 覆盖启发式 |
| `ui.hp_text` | HP 对应 OCR 文本（如 `3` 或 `3/3`），可能为 `null` |
| `game.profile` | 本次使用的 profile id；未加载 profile 时为 `null` |
| `game.provider` | 当前 provider：`vision`（已实现）；`memory` / `api` 为保留值 |
| `game.stale` | `true` = 该状态不是纯当帧视觉（含缓存/provider 旧数据，或 provider 不可用后的回退） |

### 硬规则

1. 坐标一律归一化 0..1；未知是 `null`，不是 `0`、不是 `-1`。
2. 提取器**永不抛异常**：任何失败都返回 schema 默认值（`scene: unknown`、`confidence: 0`）。
3. `game_state` 是只读的：不按键、不改窗口、不读内存。
4. 附加字段允许存在（如 `backend`）；消费方忽略不认识的字段，不因此报错。

## 3. GameProfile（游戏档案 JSON）

```json
{
  "id": "cuphead",
  "name": "Cuphead",
  "controls": {
    "left": "LEFT", "right": "RIGHT", "up": "UP", "down": "DOWN",
    "jump": "Z", "shoot": "X", "dash": "SHIFT", "confirm": "Z"
  },
  "hud": {
    "hp": {"box": [0.0, 0.9, 0.2, 0.1], "prefix": "HP"}
  },
  "scene": {
    "menu_keywords": ["START", "OPTIONS", "EXIT", "CONTINUE"],
    "death_keywords": ["DEAD", "GAME OVER", "RETRY"],
    "loading_max_texts": 1
  },
  "combat": {
    "hold": ["X"],
    "advance": "RIGHT",
    "dodge": {"keys": ["Z"], "threat_radius": 0.18, "cooldown_ms": 350},
    "stuck": {"static_mean_diff": 0.9, "after_ms": 600, "probe_ms": 350, "probe_keys": ["Z"]}
  },
  "colors": {
    "parry": {"r_min": 175, "b_min": 175, "rb_minus_g_min": 25, "min_pixels": 6}
  },
  "notes": "free text"
}
```

### 字段

| 字段 | 含义 |
|:--|:--|
| `id` / `name` | 档案 id（建议与文件名一致，安全字符 `[A-Za-z0-9._-]{1,64}`）与显示名；引擎用 `id` 填 `game.profile` |
| `controls.*` | 键位映射（`left/right/up/down/jump/shoot/dash/confirm`），取值必须是 `game_controls` 列出的键名 |
| `hud.hp.box` | `[x, y, w, h]` 归一化，相对当帧；OCR 行中心落在这个框里才算 HP 候选（未配置时不做区域过滤） |
| `hud.hp.prefix` | 可选前缀（如 `HP`），用于从 OCR 文本里裁出数值 |
| `hud.hp.max_hp` | 可选，HP 上限；用于补 `player.max_hp` |
| `scene.menu_keywords` / `death_keywords` | 场景关键词，大小写不敏感 |
| `scene.loading_max_texts` | OCR 行数在 `1..该值` 之间视为 loading（默认 1） |
| `scene.near_black_mean` | 可选，近黑画面判定阈值（0..255，默认 12） |
| `scene.prompt_keywords` / `hud.prompt_keywords` | 可选，`ui.prompt` 的候选关键词 |
| `combat.hold` | 策略常按住的键（例如射击） |
| `combat.advance` | 策略前进方向 |
| `combat.dodge` | 闪避键、威胁触发半径（归一化距离，默认 0.18）、冷却毫秒（默认 350） |
| `combat.stuck` | 卡住判定：帧差阈值（默认 0.9）、持续毫秒（默认 600）、脱困按键与时长（默认 350） |
| `combat.self_pos` / `self_radius` | 可选，归一化的自身位置与半径（默认 0.10）；威胁检测时排除自身区域 |
| `colors.parry` | 弹反点颜色阈值（`r_min` / `b_min` / `rb_minus_g_min` / `min_pixels`） |
| `notes` | 自由文本，不参与逻辑 |

规则：

- **所有键都可选**（`id` 也建议填，但引擎不强制）：缺失值回落到代码默认值，
  因此「只有键位」的最小档案也能用。
- 档案里**不放**内存偏移、CT 表、注入脚本、私服/破解文件；这些不属于 profile 的语义。
- 档案是**用户本地数据**：`$DSH_GAME_BRIDGE_PROFILE_DIR`，未设置时用
  `<cache-root>/profiles`（cache-root = `$DSH_GAME_BRIDGE_CACHE_DIR` 或系统用户缓存目录下的
  `dsh-game-bridge`）。用户档案不进仓库、不同步、不打包。
- 仓库里被跟踪的只有**通用样例**（`profiles/`，Cuphead 作为 dogfood 样例）：
  它们只含键位/HUD/阈值等公开安全字段。样例不会自动加载——用
  `DSH_GAME_BRIDGE_PROFILE_DIR` 指向 `profiles/`，或把样例 JSON 通过 `game_memory save`
  写进本地档案库后再 `game_memory use`。
- 文件名 id 校验 `[A-Za-z0-9._-]{1,64}`，拒绝路径穿越；损坏 JSON 报错，不静默覆盖。
- `game_memory save` 写入时，`data.id` 若给出必须与请求的 id 一致；缺省时自动补成
  文件名 id（避免文件内容与文件名脱节）。

## 4. provider、confidence 与 staleness

`game.provider` 是**本条状态由谁产出**，`confidence` / `score` / `stale` 是
**消费方判断能不能信的依据**。

| provider | 产出 | 何时用 | 失败策略 | 现状 |
|:--|:--|:--|:--|:--|
| `vision` | 场景、HP、弹反点、移动威胁、UI 文本 | 默认，永远可用 | 返回 unknown 默认值 | 已实现 |
| `memory` | 更准/更早的位置、实体、数值 | 用户显式启用、有本地只读适配器 | 保留视觉字段，`stale=true` | **未实现** |
| `api` | 游戏/平台只读遥测 | 用户显式启用 | 同上 | **未实现** |

合并与降级优先级：**L2 provider → L1 profile 视觉 → L0 视觉保底**。
provider 只能覆盖它声明的字段；它失败时保留下层结果，并在 `game.stale` 标记
「这里混有旧/不可靠数据」，而不是把整条状态变成错误。

- `confidence`：整条状态的可信度提示（0..1），来自场景判定的置信度；
  schema 1 **不**提供逐字段置信度，逐实体可信度看 `entities[].score`，OCR 行看 `ui.texts[].score`。
- `stale`：`false` = 纯当帧视觉；`true` = 含 provider 缓存、旧数据或 provider 不可用后的回退。
- 消费规则（对模型与策略同时成立）：
  1. 低置信度不是错误，但**不能当成确定事实**做危险决策；需要更确切时先重新 `game_state`。
  2. `stale=true` 时禁止把其中的位置/实体当成实时输入；`game_policy` 只消费当拍
     `cheap_entities`，不会用 stale 数据驱动动作。
  3. 未知就是未知：`null` 不参与距离/命中计算，策略跳过而不是猜。
  4. schema 1 不约定 provider TTL；provider 自报 `stale`，调用方不得自行假设新鲜度。

## 5. 降级与失败规则

| 失败 / 缺失 | 行为 | 用户可见 |
|:--|:--|:--|
| 引擎未就绪 / 请求超时 | 工具如实报错，不伪造状态 | `game_state` 返回错误文本；`game_snapshot` 用合成帧并写明原因 |
| 抓屏失败（无帧） | WorldState schema 默认值（`scene: unknown`、`confidence: 0`） | 不显示假的 HP/实体 |
| OCR 不可用或没有文本 | 文本类字段为空；场景退化为近黑/unknown 判定 | `ui.texts: []` |
| profile 缺失/损坏 | 视觉保底 + 代码默认阈值；`game.profile: null` | 状态仍可用，提示无档案 |
| profile 字段缺失 | 该字段用代码默认值 | 无感 |
| 实体检测无结果 | `entities: []` | 策略不闪避，只保持基础动作 |
| provider 超时 / 不可用 | 视觉保底 + `game.stale: true`（若曾使用 provider 数据） | 文本提示 stale |
| 遮挡 / 目标不在前台 | 状态照常产出，附 `foreground` / `occluded` | 工具文本打 `⚠`，不假装看见 |
| 非法帧 / 垃圾输入 / 尺寸异常 | 返回 schema 默认值，**不抛** | — |
| 安全闸拒绝输出 | 与状态无关：策略停止并记 `stop_reason`，按键全部释放 | `game_policy` / `game_status` 显示 blocked 原因 |

原则：**降级只降低精度，不制造幻觉**。任何「不知道」都用 `unknown` / `null` /
空数组表达；工具文本必须说清是哪一层失败了。

## 6. 安全边界

状态层不改变既有的四道硬闸，只增加数据边界：

1. **默认只读**：v1 不读游戏内存、不注入进程；WorldState 全部来自抓屏 + OCR。
   `game_memory` 是**本地档案存储**，不是内存读取器。
2. **反作弊不接**：命中 EAC / BattlEye / Vanguard / ACE 等进程即拒绝一切输出；
   未来的 memory/API provider 同样不接线，不得绕过。
3. **真实后端需批准**：非 dry-run 后端在 `game_attach` 时走 DSH 一次性审批；
   attach 后动作前校验前台窗口，`FOREGROUND_MISMATCH` 直接拒绝；F12 随时夺回。
4. **档案边界**：被跟踪的 profile 只含通用键位/HUD/阈值；内存偏移/攻略数据即使将来
   加入，也只能留在用户本地档案，默认关闭、显式启用、不随仓库分发。
5. **公开边界**：仓库不出现游戏内存地址、CT 表、私服/破解文件、本机用户名或路径。
6. **隐私**：帧只经宿主 attachment 进会话，不额外写文件；审计日志默认关闭，
   路径由用户指定。

## 7. 工具映射

| 工具 | 参数 | 与状态模型的关系 |
|:--|:--|:--|
| `game_attach` | `window`，可选 `profile` | 绑定窗口（授权步骤）；带 `profile` 时记住 `runtime.profileId`；profile 缺失不导致 attach 失败 |
| `game_state` | 无 | 按当前 profile 调引擎 `state`，返回 §2 的 WorldState；渲染一行摘要（`scene=…, hp=…, entities=N, prompt=…`）并附前台/遮挡警告 |
| `game_policy` | `action`: `start` / `stop` / `status` | `start` 用当前 profile 起 60 Hz `PolicyRunner`（需先 attach，否则 `NOT_ATTACHED`）；`stop` 松手并返回最终统计；输出 `policy` JSON（running / ticks / hz / actions / escapes / stop_reason / scene / last_entities） |
| `game_memory` | `action`: `list` / `get` / `save` / `delete` / `use`，`id`，`data` | 操作 §3 的本地档案库；`save` 校验 id 与 JSON，`use` 设置当前 `runtime.profileId`。**不读游戏内存** |
| `game_plan` | 方向键 + 时长 | 20 Hz 有界方向闭环（hold/tap/advance），不吃 WorldState；与 `game_policy` 是两种分工 |
| `game_snapshot` | 无 | 原始帧 + OCR，不是状态模型；排查「状态为什么不对」时用它看原图 |
| `game_status` | 无 | 汇总绑定/安全/闭环/策略进度，Agent 轮询用 |
| `game_stop` | 无 | 停一切、松手、解绑；`game_memory` 不受影响 |

典型顺序：

```
game_attach(window="…", profile="cuphead")
  → game_state                 # 看一眼：scene / hp / entities
  → game_policy action=start   # 60 Hz 反射（射击/前进/闪避/脱困）
  → game_status                # 稀疏轮询
  → game_policy action=stop    # 或 game_stop
```

`game_state` 与 `game_policy` 是**低频工具 + 本地高频循环**的分工：模型看状态、
决定起停；反射动作留在本地，不逐步调用工具。

## 8. 验证

- 引擎：`engine/tests/test_state.py`（HP 区域/前缀、场景优先级、合成粉色弹反图、
  合成移动威胁、垃圾输入不崩）、`test_policy.py`（安全中止、闪避冷却、脱困、松手、status 形状）。
- 插件：`test/general-state.test.mjs` 与 `test/m0.test.mjs`（工具列表、渲染路径、档案库）。
- 全量回归与真实对局验证由 Lead 执行；`docs/STATUS.md` 只记录已验证的事实。
