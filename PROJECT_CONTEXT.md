# 小豆芽自动发布脚本 — AI 上下文文档

本文档是给 Trae / AI 助手阅读的项目知识库，包含两个脚本的完整架构、业务流程、已知 BUG 及修复方法。阅读本文后即可理解项目全貌并定位问题。

---

## 1. 项目概述

本仓库包含两个基于 pywinauto 的 RPA 脚本，通过 `新榜小豆芽` 客户端自动发布短视频：

| 脚本 | 平台 | 入口 |
|------|------|------|
| `xiaodouya_poster.py` | 抖音 | `xiaodouya_launcher.py` → `启动抖音自动发布.bat` |
| `xhs_xiaodouya_poster.py` | 小红书 | `xhs_xiaodouya_launcher.py` → `启动小红书自动发布.bat` |

**两个脚本互不共用代码逻辑，修改其中一个不得顺带改动另一个。**

---

## 2. 文件结构

```
Trae Pro/                          # 源代码根目录
├── xiaodouya_poster.py            # 抖音主脚本（~1225行）
├── xiaodouya_launcher.py          # 抖音启动器（交互式选择账号/话题）
├── xiaodouya_config.example.json  # 抖音配置模板
├── 启动抖音自动发布.bat            # 抖音一键启动
├── xhs_xiaodouya_poster.py        # 小红书主脚本（~1042行）
├── xhs_xiaodouya_launcher.py      # 小红书启动器（交互式选择账号）
├── xhs_xiaodouya_config.example.json # 小红书配置模板
├── 启动小红书自动发布.bat          # 小红书一键启动
├── requirements.txt               # Python依赖
├── PROJECT_CONTEXT.md             # 本文档
├── 开发与BUG备忘录.md              # 开发过程中的踩坑记录
├── README.md                      # 用户向说明
├── rename_mahjong_videos.py       # 辅助：麻将视频批量重命名
├── rename_xhs_videos.py           # 辅助：小红书视频批量重命名
└── remove_text_from_videos.py     # 辅助：视频去文字
```

**运行时产生的文件**（已 gitignore）：
- `xiaodouya_config.json` / `xhs_xiaodouya_config.json` — 真实配置
- `error_log.txt` / `xhs_error_log.txt` — 错误日志
- `published_history.txt` — 抖音已发布记录
- `xhs_publish_plan_YYYYMMDD.txt` — 小红书发布清单（带 down 标记）
- `*.log`, `trace.txt`, `run_output.txt` 等

---

## 3. 抖音脚本 (xiaodouya_poster.py) 完整架构

### 3.1 Config 数据类

```python
@dataclass
class Config:
    source_dir: Path        # 待发布视频目录
    published_dir: Path     # 已发布视频归档目录
    app_exe: str            # 小豆芽安装路径
    account_prefixes: list  # 账号列表 ["01号","02号",...]
    task_title: str         # 小豆芽任务名称
    hashtags: list          # 固定话题列表
    single_run: bool        # True=只跑一遍, False=循环轮转
    publish_delay_sec: float # 发布后等待秒数
```

### 3.2 核心类 XiaodouyaPoster — 关键方法调用链

```
run()
 ├── start_hotkey_listener()      # 注册 Ctrl+T 全局热键终止
 ├── ensure_app_window()          # 定位小豆芽窗口 → 2560×1600 强制尺寸
 ├── sync_already_published_files() # 去重：删除已发布过的残留文件
 ├── list_videos()                # 扫描 source_dir 中的视频文件
 ├── build_assignments()          # 按 single_run 决定账号分配策略
 └── for each (account, video):
       ├── check_abort()          # 每步检查 Ctrl+T
       ├── publish_one()
       │   ├── click_account()        # 点击左侧账号名（含悬浮窗消除）
       │   ├── goto_my_task()         # 展开"变现中心"→点击"我的任务"
       │   ├── click_task_detail()    # 找到目标任务→点击"查看详情"
       │   ├── click_upload_video_entry() # 点击红色"上传视频"
       │   ├── upload_file()          # Windows文件框→填路径→回车
       │   ├── set_title_from_filename() # 标题=文件名+话题逐个填写
       │   ├── apply_first_ai_cover()  # 点击第一张智能封面→确定
       │   ├── scroll_to_publish()     # 滚动到底部
       │   ├── ensure_immediate_publish() # 点击"立即发布"
       │   └── final_publish()         # 点击最终"发布"按钮
       ├── record_published()     # 写入 published_history.txt
       └── move_to_published()    # 移动视频到已发布目录
```

### 3.3 窗口定位逻辑

```python
WINDOW_X, WINDOW_Y = 50, 50
WINDOW_WIDTH, WINDOW_HEIGHT = 2560, 1600   # 硬编码！必须匹配屏幕分辨率
```

`position_app_window()` 使用 `win32gui.SetWindowPos` 将小豆芽窗口强制设为上述尺寸。如果对方屏幕分辨率小于 2560×1600，所有基于绝对坐标的 click 会偏移。这是**最常见的部署问题**。

### 3.4 状态机等待模式

脚本在三个关键节点使用状态检测而非盲目 sleep：

1. **上传入口点击后** → `wait_task_detail_ready()` 轮询检测三种状态：`"task_detail"` / `"editor"` / `"dialog"`
2. **文件选择框** → `wait_open_dialog()` 扫描 "打开"/"Open" 标题窗口
3. **发布编辑页** → `is_publish_editor_page()` 检测 `"填写作品标题，为作品获得更多流量"` 占位文本

---

## 4. 小红书脚本 (xhs_xiaodouya_poster.py) 完整架构

### 4.1 Config 数据类

```python
@dataclass
class Config:
    app_exe: str
    source_dir: Path
    published_dir: Path
    collection_name: str            # 小红书合集名，如 "天天麻将小红书"
    account_prefixes: list          # 如 ["H01","H02",...]
    publish_per_account: int        # 每账号发几条
    description_text: str           # 固定正文文案
    publish_delay_sec: float
    upload_wait_sec: float
    single_account_mode: bool       # True=只跑 single_account
    single_account: str             # 单账号模式下的目标账号
```

### 4.2 核心类 XiaodouyaXhsPoster — 关键方法调用链

```
run()
 ├── start_hotkey_listener()
 ├── validate_environment()     # 检查 source_dir 存在，创建 published_dir
 ├── ensure_app_window()        # 2560×1600 强制尺寸
 ├── build_tasks()              # 按文件名排序，H01-H12 轮转分配
 │   ├── write_task_plan()      # 生成 xhs_publish_plan_YYYYMMDD.txt 清单
 │   └── read_done_video_names_from_plan() # 读取已有 down 标记
 └── for each (task_index, account, video):
       ├── check_abort()
       ├── is_task_done()           # 跳过已有 down 标记的任务
       ├── publish_one()
       │   ├── click_text(["多开面板"])   # 先点多开面板
       │   ├── ensure_collection_expanded() # 展开合集→显示H01-H12
       │   ├── click_account(prefix)       # 双击+Hover清除悬浮窗
       │   ├── click_publish_note()        # 点击"发布笔记"
       │   ├── click_upload_video()        # 多种方式打开文件框
       │   ├── upload_file()               # 同抖音：填路径→回车
       │   ├── fill_title_and_description() # 标题=文件名，正文=配置文案
       │   ├── scroll_to_bottom()
       │   └── click_final_publish()       # 最多重试8次
       ├── mark_task_done()        # 在清单中追加 "down"
       └── move_to_published()
```

### 4.3 发布清单机制

小红书脚本在 `source_dir` 目录生成带日期的清单文件：
- 格式：`xhs_publish_plan_20260511.txt`
- 内容：每行 `001. H01 -> 视频名.mp4`，发布成功后追加 ` down`
- 重跑时会跳过已有 `down` 标记的行
- 清单条目数 = 当前素材目录的视频总数（不限制数量）

### 4.4 上传对话框兜底策略

`open_upload_dialog()` 使用三层兜底：
1. 直接命中 "上传视频" / "点击上传" Button 文本
2. 按 "拖拽视频到此或点击上传" 锚点定位下方红色按钮区域
3. 文本点击兜底：`click_text(["上传视频"])`

---

## 5. 配置文件详解

### 5.1 抖音配置 (xiaodouya_config.json)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `app_exe` | string | 否 | 小豆芽安装路径，默认 `C:\Program Files\xiaodouya\新榜小豆芽.exe` |
| `source_dir` | string | 是 | 待发布视频目录，支持相对路径如 `.\素材` |
| `published_dir` | string | 是 | 已发布归档目录，支持相对路径如 `.\已发布` |
| `task_title` | string | 是 | 小豆芽中显示的任务名称，如 `"三国冰河时代矩阵短视频"` |
| `account_prefixes` | [string] | 是 | 账号列表，格式 `"01号"` |
| `hashtags` | [string] | 否 | 话题列表，如 `["#话题1","#话题2","#话题3"]` |
| `single_run` | bool | 否 | 默认 false；true 时按视频数量取前N个账号各发一条 |
| `publish_delay_sec` | number | 否 | 发布后等待秒数，默认 6 |

### 5.2 小红书配置 (xhs_xiaodouya_config.json)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `app_exe` | string | 否 | 同上 |
| `source_dir` | string | 是 | 待发布视频目录 |
| `published_dir` | string | 是 | 已发布归档目录 |
| `collection_name` | string | 是 | 小豆芽中小红书合集名，如 `"天天麻将小红书"` |
| `account_prefixes` | [string] | 是 | 账号列表，格式 `"H01"` |
| `publish_per_account` | number | 否 | 每账号发几条，默认 1 |
| `description_text` | string | 否 | 正文/描述文案 |
| `publish_delay_sec` | number | 否 | 发布后等待秒数 |
| `upload_wait_sec` | number | 否 | 上传后等待秒数 |
| `single_account_mode` | bool | 否 | 单账号模式开关 |
| `single_account` | string | 否 | 单账号模式目标 |

---

## 6. 两个脚本的关键差异

| 维度 | 抖音 | 小红书 |
|------|------|--------|
| 导航入口 | 变现中心→我的任务→查看详情→上传视频 | 多开面板→合集→账号→发布笔记→上传 |
| 标题来源 | 视频文件名（去后缀） | 视频文件名（去后缀） |
| 文案/话题 | 标题框+独立"#添加话题"逐个填入 | 标题框+正文描述框，固定配置文案 |
| 封面 | Ai智能推荐封面→点击第一张→确定 | 无封面操作 |
| 发布按钮 | "发布"（立即发布+最终发布两步） | "发布"（可重试8次） |
| 账号格式 | `01号` ~ `99号` | `H01` ~ `H12` |
| 去重/续跑 | `published_history.txt` | `xhs_publish_plan_YYYYMMDD.txt` + `down` |
| 文件移动重试 | 最多10次，每5秒 | 最多2次，每1秒 |
| launch交互 | 可选自定义话题词 | 不可自定义话题词 |
| 已发布检查 | 按文件名去重 | 按文件名+清单 down 标记 |

---

## 7. 已知 BUG 汇总与修复方法

### BUG-1: 悬浮资料卡遮挡导致账号误触

**现象**：在左侧列表点击账号名时，小豆芽会弹出该账号的悬浮资料卡，遮挡后续点击位置。如果盲目点击屏幕下方消除弹窗，可能误触排在下方的其他账号。

**错误尝试**：尝试点击屏幕下方 `(200, 800)` 的绝对坐标消除弹窗。

**修复代码位置**：`click_account()` 方法（抖音 L455-505，小红书 L478-511）

**修复逻辑**（已落地）：
1. 点击账号名两次（第一次触发悬浮窗，第二次进入页面）
2. 在左侧菜单中找到 "任务市场" 文本按钮的底部坐标
3. 在 "任务市场" 正下方 30 像素的空白区域点击鼠标左键，消除悬浮窗
4. 该区域永远是安全的空白区

**如需调整**：修改 `safe_click_y = rect.bottom + 30` 中的 30 像素偏移量。

---

### BUG-2: 找不到"我的任务"入口

**现象**：脚本报错 "未找到'我的任务'入口"。

**原因分析**：
- 小豆芽在 `SetForegroundWindow` 时可能退出最大化，导致侧边栏变形
- "我的任务" 是二级菜单，必须先展开 "变现中心"

**修复代码位置**：`goto_my_task()` 方法（抖音 L507-645）

**修复逻辑**（已落地）：
1. 所有窗口激活用 `win32gui.ShowWindow(hwnd, SW_MAXIMIZE)` 强制全屏
2. 先查找 "变现中心" 一级菜单，点击文字偏左位置（避开右侧折叠箭头）
3. 展开后再查找 "我的任务"
4. 如果仍然找不到，暴力关闭所有标签页后重新从左侧进入

**如需调整**：如果小豆芽更新后 "变现中心" 改名，在 L524 的 `"变现中心" in name` 中修改匹配文本。

---

### BUG-3: 详情页白屏卡死 / 页面迷失

**现象**：点击 "查看详情" 后页面卡在白屏，或停留在之前未完成的发布页。

**修复代码位置**：`goto_my_task()` 方法中 L578-620

**修复逻辑**（已落地）：
1. 扫描页面上所有 `control_type == "Button"` 且 name 含 "关闭" 的控件
2. 逐个点击关闭，最多关闭 3 个标签页
3. 重新从左侧账号列表进入，确保从干净首页开始
4. 再次展开变现中心→我的任务

---

### BUG-4: "上传视频"按钮找不到（坐标过滤误伤）

**现象**：在任务详情页找不到 "上传视频" 按钮。

**原因**：早期代码为过滤创作者主页的顶部上传按钮，加了 `min_left=1200` 的横坐标限制。但在任务详情页中上传按钮在偏左下方，被该条件过滤。

**修复**：已彻底删除 `min_left` 限制条件。

**如需调整**：检查 `click_upload_video_entry()` 中的过滤条件，确保没有多余的坐标限制。

---

### BUG-5: Windows 文件选择对话框点击"打开"无反应

**现象**：填入视频路径后鼠标点击 "打开(O)" 按钮无反应。

**原因**：焦点丢失或 UIA 与 Win32 后端交互差异，mouse.click() 未触发系统确认事件。

**修复代码位置**：`upload_file()` 方法（抖音 L915-941，小红书 L789-826）

**修复逻辑**（已落地）：
1. 用 `file_name_edit.set_edit_text(str(video_path.resolve()))` 填入绝对路径
2. 使用 `keyboard.send_keys("{ENTER}")` 敲回车代替点击按钮
3. 等待对话框 `wait_not("visible", timeout=30)` 消失
4. （小红书额外）`wait_upload_ready()` 检测 "重新上传"/"更换视频"/"封面" 等关键词确认上传完成

---

### BUG-6: 弹窗挡住封面 / 话题加不进标题

**现象1**：点击智能推荐封面后，"确定"按钮被 "智能封面已上线" 新手引导弹窗挡住。

**修复**：`clear_onboarding_popups()` 函数（抖音 L943-955），在操作前扫描并点击 "我知道了"、"关闭"、"确定" 按钮。

**现象2**：标题行字数超限导致 `#话题` 拼接在标题后面被截断。

**修复**：拆分填写。标题只填文件名，话题通过点击独立的 "#添加话题" 文字按钮，在独立输入框内逐个粘贴话题并回车激活蓝色标签。

**如需调整**：如果出现新的弹窗文案，在 `clear_onboarding_popups()` 的 `name in (...)` 中添加新文案。

---

### BUG-7: 文件移动失败 — PermissionError

**现象**：`[Errno 13] Permission denied` 或文件被小豆芽后台进程占用。

**修复代码位置**：`move_to_published()` 方法（抖音 L1168-1201，小红书 L995-1013）

**修复逻辑**（已落地）：
1. Python `shutil.move` 失败后等待 5 秒重试，最多 10 次（抖音）/ 2 次（小红书）
2. 如果 Python 方式全失败，调用系统底层 `os.system('move /Y ...')` 强行移动
3. 如果仍失败，不中断流程，打印警告继续

---

### BUG-8: 抖音上传阶段卡住（状态机相关）

**现象**：上传视频入口被重复点击，或旧页面判断导致卡住。

**修复代码位置**：`click_upload_video_entry()` 方法（抖音 L827-891）

**修复逻辑**（已落地）：
1. 先检测是否已在 "作品编辑页" → 是则跳过
2. 再检测文件框是否已打开 → 是则跳过
3. 只在确认不在以上两个状态时才点击 "上传视频"
4. 点击后等待文件框出现或编辑页出现

---

### BUG-9: 小红书文件框打开后找不到控件

**现象**：部分 Windows 系统/版本下，文件选择对话框的结构与通用模板不同。

**修复代码位置**：`find_open_dialog_filename_edit()`, `find_open_dialog_confirm_button()`, `open_upload_dialog()` 方法（小红书 L594-787）

**修复逻辑**（已落地）：
1. `find_open_dialog_filename_edit()` 遍历子窗口，按 Edit 类型 + 可见 + 底部区域 + 宽度 ≥120 找文件名输入框
2. `find_open_dialog_confirm_button()` 在 Button 中按 "打开"/"确定" 文案匹配
3. `open_upload_dialog()` 使用了三层兜底策略（见 4.4 节）
4. 异常时调用 `dump_open_dialog_controls()` 导出控件树到 `xhs_open_dialog_dump.txt` 便于排查

---

### BUG-10: 分辨率/缩放不匹配导致点击偏移

**现象**：脚本点不到按钮，或点击位置偏差很大。

**原因**：两个脚本硬编码了窗口尺寸 2560×1600，所有 `mouse.click(coords=...)` 基于此坐标计算。如果 Windows 显示缩放不是 100%，或屏幕分辨率低于此值，坐标会严重偏移。

**必须满足的条件**：
- Windows 显示设置 → 缩放 = **100%**
- 屏幕分辨率 ≥ 2560×1440（推荐 2560×1600）
- 如果屏幕只有 1920×1080，需要修改两个脚本中所有 `WINDOW_WIDTH` 和 `WINDOW_HEIGHT` 常量，以及所有硬编码的坐标值（`coords=(1600, 900)` 等）

**涉及位置**：
- `WINDOW_WIDTH = 2560`, `WINDOW_HEIGHT = 1600`（抖音 L41-42，小红书 L24-25）
- 所有 `mouse.scroll(coords=(1600, ...))` 中的 1600（多个位置）
- `mouse.scroll(coords=(350, ...))` 中的 350（左栏滚动）
- `is_publish_editor_page()` 中的 `rect.left > 1100` / `rect.left > 1400`（抖音 L320-323, L1077, L1090）
- `set_title_from_filename()` 中的 `rect.left > 1100`（抖音 L998）
- `open_upload_dialog()` 中的 `420 <= cx <= 2280 and 180 <= cy <= 1400`（小红书 L705）

---

### BUG-11: 启动器账号校验失败

**现象**：配置了账号却报 "账号格式不合法"。

**原因**：
- 抖音启动器 `normalize_account()` 要求输入纯数字，如 `"01","02"`（不能带"号"字也不能是字母）
- 小红书启动器要求 `H` 开头后跟 1-12 的数字，如 `"H01","H2"`

**修复**：确保配置文件中的 `account_prefixes` 格式正确：
- 抖音：`["01号","02号"]`（json 中必须带"号"，但 launcher 交互输入时只需 `01,02`）
- 小红书：`["H01","H02"]`

---

### BUG-12: 小红书清单写入 PermissionError

**现象**：`警告：清单文件写入失败（PermissionError...）`。

**原因**：`source_dir` 目录权限不足，或被其他程序占用。

**修复逻辑**：`write_task_plan()` 方法有三级目录候选：
1. `source_dir` 下（首选）
2. `source_dir` 下带时间戳的备份名
3. `application_path`（脚本所在目录）

**如需调整**：增加更多候选目录或调整文件写入权限要求。

---

## 8. 环境部署检查清单

部署到新电脑时，按以下顺序检查：

### 8.1 Python 环境
```powershell
# 确认 Python 3.x 已安装
python --version

# 安装依赖
pip install -r requirements.txt
# 依赖: pywinauto==0.6.9, pywin32==311
```

### 8.2 小豆芽客户端
- 确认已安装，能找到 `新榜小豆芽.exe`
- 查找方法：桌面快捷方式 → 右键属性 → "目标" 路径
- 将路径填入 `xiaodouya_config.json` 和 `xhs_xiaodouya_config.json` 的 `app_exe`

### 8.3 Windows 系统设置
- **显示缩放 = 100%**（最重要！）
- 屏幕分辨率 ≥ 2560×1440
- 如果分辨率不足，必须修改脚本中的窗口尺寸常量

### 8.4 配置文件
1. 复制 `*.example.json` → `*.json`
2. 修改 `source_dir`、`published_dir` 为实际路径
3. 修改 `task_title`（抖音）或 `collection_name`（小红书）
4. 修改 `account_prefixes` 为实际账号

### 8.5 素材准备
- 抖音素材 → `source_dir`（相对于 config 中的路径）
- 小红书素材 → `source_dir`（相对于 config 中的路径）
- 支持格式：`.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`

### 8.6 运行前
- 必须**先手动打开小豆芽并登录**
- 确认小豆芽窗口正常显示（不要最小化）
- 脚本运行期间不要操作鼠标和键盘

---

## 9. 运行时常见故障排查表

| 现象 | 可能原因 | 解决方法 |
|------|----------|----------|
| `未找到 新榜小豆芽 窗口` | 小豆芽未打开或已最小化 | 手动打开并保持前台 |
| 按钮点不到/点偏 | 缩放≠100%或分辨率不足 | 调至100%缩放，确认分辨率≥2560×1440 |
| `未找到账号：xx` | 账号名不匹配或列表未展开 | 检查 config 中账号前缀是否正确 |
| `未找到任务详情按钮` | task_title 不匹配 | 确认 config 中的 task_title 与小豆芽显示一致 |
| `未找到“我的任务”入口` | 变现中心未展开或页面卡死 | 手动展开变现中心，或在小豆芽中关闭多余标签页后重试 |
| 文件选择框不消失 | 小豆芽上传卡住 | Ctrl+T 终止，检查视频文件是否过大 |
| `PermissionError` | 视频文件被占用 | 等待释放或手动移动 |
| 发布后视频未移动 | 文件被占用 | 手动移入"已发布"目录，不影响下次运行 |
| 出现验证码/登录弹窗 | 平台风控 | 先人工处理验证码，确认在线后重跑 |
| `视频文件不存在` | 路径配置错误或文件已发布 | 检查 source_dir 路径和素材目录 |
| 小红书清单写入失败 | 目录权限问题 | 检查 source_dir 目录权限 |
| launcher报 `账号格式不合法` | 输入格式错误 | 抖音用 `01,02`，小红书用 `H01,H02` |

---

## 10. 调试与诊断工具

### 10.1 Ctrl+T 紧急终止
两个脚本均注册了全局热键 `Ctrl+T`，按下后立即终止脚本（通过 `os._exit(130)`）。

### 10.2 错误日志
- 抖音错误 → `error_log.txt`
- 小红书错误 → `xhs_error_log.txt`
- 小红书文件框诊断 → `xhs_open_dialog_dump.txt`

### 10.3 UI 控件导出
`dump_ui.py` 可导出小豆芽窗口的完整 UIA 控件树，用于排查元素定位问题。

### 10.4 已发布记录
- 抖音：`published_history.txt` 格式 `时间|账号|文件名`
- 小红书：`xhs_publish_plan_YYYYMMDD.txt` 格式 `序号. 账号 -> 文件名 down`

---

## 11. 打包说明

`xiaodouya_release_build_fix_v3/` 目录包含 PyInstaller 打包产物：
- `dist/xiaodouya_poster.exe` — 抖音脚本的独立可执行文件
- `spec/xiaodouya_poster.spec` — PyInstaller 规格文件
- 打包命令：`pyinstaller xiaodouya_poster.spec`

注意：exe 版本是通过 PyInstaller 将 Python 解释器和依赖一并打包，**不依赖本地 Python 环境**。但如果要调试或修改代码，建议使用源码 `py` 方式运行。

---

## 12. 开发约定

1. **两个脚本互不共用代码**：修改抖音脚本时不得顺带改动小红书脚本，反之亦然。
2. **所有窗口激活用 `ShowWindow(SW_MAXIMIZE)`**：不要使用其他最大化方式，防止页面布局变化。
3. **mouse.click 优先用相对坐标**：基于控件 `element_info.rectangle` 计算中心点，不要硬编码绝对坐标。
4. **每次操作前 refresh_window()**：确保 UIA 树是最新的。
5. **每步操作后 check_abort()**：确保 Ctrl+T 能及时响应。
6. **异常时先写日志再抛出**：`error_log.txt` / `xhs_error_log.txt` 是主要的故障定位手段。
7. **文件移动用重试+系统命令兜底**：不要因为移动失败而让脚本崩溃，已发成功的视频通过 `publish_button_clicked` / `publish_confirmed` 标记为成功。
