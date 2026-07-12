# battle-cat-automator

**This repo is done by Codex with my idea. Use as your own risk.**

最小流程：

```text
MaaFramework/Python -> 截图 -> 找按钮 -> 点击
```

## 换电脑部署

前提：

```text
Windows
uv
scrcpy / adb
Android USB 调试
```

安装依赖：

```powershell
uv sync
```

如果 `adb` 不在 PATH，可以指定 scrcpy 自带的 `adb.exe`：

```powershell
$env:BCA_ADB_PATH = "D:\Custom Programs\scrcpy-win64-v3.3.3\adb.exe"
```

检查截图链路：

```powershell
uv run python tools/capture.py
```

## 准备

1. 手机开启 USB 调试。
2. 确认 `scrcpy` 能看到手机画面。
3. 在这个目录运行：

```powershell
uv sync
uv run python tools/capture.py
```

截图会保存到 `captures/latest.png`。

如果当前终端还没识别 winget 新装的 `scrcpy` / `adb`，可以临时指定 ADB 路径：

```powershell
$env:BCA_ADB_PATH = "D:\Custom Programs\scrcpy-win64-v3.3.3\adb.exe"
uv run python tools/capture.py
```

## 点击一个按钮

先从 `captures/latest.png` 里裁一张按钮小图，放到：

```text
resource/image/target_button.png
```

然后运行：

```powershell
uv run python tools/click_template.py
```

默认会用 MaaFramework 的 `TemplateMatch` 找到 `target_button.png`，然后点击匹配区域中心。

## 固定关卡自动战斗

当前最小闭环只面向：

```text
pacman_cookie_01
コラボステージ / パックマン登場！ / 迷路に並んだクッキー
```

手机需要手动停在这个关卡的出击前页面。需要准备这些模板：

```text
resource/image/pacman_cookie_01/stage_ready_marker.png
resource/image/pacman_cookie_01/start_button.png
resource/image/pacman_cookie_01/battle_ui_marker.png
resource/image/pacman_cookie_01/victory.png
resource/image/pacman_cookie_01/result_map_button.png
resource/image/pacman_cookie_01/leadership_restore_dialog.png
resource/image/pacman_cookie_01/ex_stage_prompt.png
```

还需要在战斗截图上确定第 5 个出战槽位的点击坐标，然后创建：

```text
resource/config/pacman_cookie_01.json
```

格式：

```json
{
  "slot5": {
    "x": 1079,
    "y": 554
  },
  "result_safe_click": {
    "x": 100,
    "y": 100
  },
  "leadership_restore_yes": {
    "x": 631,
    "y": 470
  },
  "ex_stage_yes": {
    "x": 640,
    "y": 467
  }
}
```

运行：

```powershell
uv run python tools/run_pacman_cookie_01.py
```

第一版战斗策略是固定点击第 5 个出战槽位。槽位可用状态识别先保留为后续 TODO。

当前完整流程：

```text
STAGE_READY -> BATTLE_LOADING -> BATTLE -> WAIT_FOR_VICTORY -> RESULT -> FINAL_RESULT -> FINISHED
```

战斗中只点击一次第 5 号位，然后等待 `victory.png`。如果胜利后有奖励弹窗，会点击 `result_safe_click` 位置关闭覆盖层，直到检测到 `result_map_button.png`。

每次截图后会先处理高优先级中断：

```text
leadership_restore_dialog -> click leadership_restore_yes -> UNKNOWN
ex_stage_prompt -> click ex_stage_yes -> BATTLE_LOADING
```

`battle_ui_marker.png` 只使用左上角暂停按钮，不绑定具体关卡名，所以普通关和随机 EX 关共用同一套 `BATTLE_LOADING -> BATTLE -> WAIT_FOR_VICTORY`。

只验证出击前页面并点击进入战斗：

```powershell
uv run python tools/build_pacman_cookie_01_templates.py
uv run python tools/run_pacman_cookie_01.py --start-only
```

## Event Gacha

手动进入活动 Gacha 页面后运行：

```powershell
uv run python tools/build_event_gacha_templates.py
uv run python tools/run_event_gacha.py --runs 1
```

`--runs N` 表示成功完成 N 次十连。计数发生在一轮抽卡所有 OK 页面点完，并重新检测到 Gacha 页面后。

动画跳过策略：

```text
点击十连后先等待 --initial-animation-wait，默认 2.0 秒
结果页 OK 后先等待 --post-ok-ready-wait，默认 1.2 秒
如果这时还没回到 Gacha 页面，再按 --skip-animation-delay 安排一次跳过点击
```

如果长时间既检测不到结果页 OK，也检测不到 Gacha 页面，会保存 debug 截图到 `captures/debug` 并停止。

最快固定点版本：

```powershell
uv run python tools/run_event_gacha_fast_click.py --clicks 80
```

默认点击点是 `(1240, 600)`，位于十连按钮和结果 OK 按钮的重叠可点击区域。需要调速时使用 `--interval`。
