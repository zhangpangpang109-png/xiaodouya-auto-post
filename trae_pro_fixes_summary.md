# Trae Pro 项目总结 & BUG修复记录

## 项目概述

基于 pywinauto 的 RPA 自动化脚本仓库，操控"新榜小豆芽"桌面客户端实现抖音和小红书两个平台的短视频批量自动发布。

### 核心文件

| 文件 | 说明 |
|------|------|
| `xiaodouya_poster.py` | 抖音自动发布主脚本（~1258行） |
| `xiaodouya_launcher.py` | 抖音启动器（交互式选择账号/话题） |
| `xhs_xiaodouya_poster.py` | 小红书自动发布主脚本（~1042行） |
| `xhs_xiaodouya_launcher.py` | 小红书启动器 |
| `PROJECT_CONTEXT.md` | AI 知识库文档（架构+12个已知BUG+修复方法） |
| `开发与BUG备忘录.md` | 开发踩坑记录 |

### 抖音发布主流程

```
run() → click_account() → goto_my_task() → click_task_detail()
→ click_upload_video_entry() → upload_file() → set_title_from_filename()
→ apply_first_ai_cover() → scroll_to_publish() → final_publish()
```

所有坐标硬编码为 2560×1600，Windows 缩放必须 100%。

---

## BUG修复 #1：后续账号无法进入"我的任务"

### 现象
- 01号账号偶发性能点击"变现中心→我的任务"
- 02、03、04...后续账号必然失灵
- 错误日志：`RuntimeError: 点击"查看详情"后未进入可上传页面。`

### 根因
`goto_my_task()` 方法（L507）的 Phase 0 循环逻辑顺序错误。

折叠状态下，小豆芽 UIA 树中"我的任务"文本节点**仍然存在**（只是不可见）。原代码 Phase 0 每轮迭代先检查"我的任务"→ 找到了 → 直接 break 退出，完全跳过展开"变现中心"的步骤。后续点击不可见元素的坐标，什么都没发生。

### 修复
**文件**: `xiaodouya_poster.py` → `goto_my_task()` Phase 0（L507-537）

**改动**: Phase 0 循环内交换查找顺序：**先展开变现中心，再找我的任务**。

```python
# 修复前：先找"我的任务"→找到了就跳过变现中心展开
for _ in range(10):
    target = find("我的任务")
    if target: break        # ← BUG: 折叠状态下也能找到
    monetize = find("变现中心")
    if monetize: click()    # ← 永远走不到

# 修复后：先展开变现中心，再找我的任务
for _ in range(10):
    monetize = find("变现中心")
    if monetize: click()    # ← 确保展开
    target = find("我的任务")
    if target: break
```

其余代码（Phase 1、Phase 2、暴力关闭标签页兜底）均未改动。

---

## BUG修复 #2：第一个话题词填入了视频标题

### 现象
预设 3 个话题词中，第一个话题词大概率被填成视频标题（文件名），后面两个正确。

### 根因
`set_title_from_filename()` 的话题循环（L1073-1082）中，`copy_text(tag)` 通过 win32clipboard 写入剪贴板后立即 `send_keys("^v")`，中间零延迟。`CloseClipboard` 后剪贴板需极短时间才能被外部进程读取，此时 `^v` 读到的是上一次剪贴板内容——即刚粘贴完的标题。

标题写入没出同类问题是因为它前面有 `^a{BACKSPACE}` + `sleep(0.2)` 自然间隔开了。

### 修复
**文件**: `xiaodouya_poster.py` → `set_title_from_filename()` L1078-1079

**改动**: `copy_text(tag)` 后加 `time.sleep(0.15)`，给剪贴板写入完成的时间。

```python
# 修复前
copy_text(tag)
keyboard.send_keys("^v")

# 修复后
copy_text(tag)
time.sleep(0.15)
keyboard.send_keys("^v")
```