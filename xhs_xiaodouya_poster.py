import json
import os
import random
import re
import shutil
import sys
import time
import ctypes
import threading
from dataclasses import dataclass
from pathlib import Path

import win32con
import win32clipboard
import win32gui
import win32com.client
from pywinauto import Desktop, keyboard, mouse


APP_TITLE = "新榜小豆芽"
DEFAULT_APP_EXE = r"C:\Program Files\xiaodouya\新榜小豆芽.exe"
WINDOW_X = 50
WINDOW_Y = 50
WINDOW_WIDTH = 2560
WINDOW_HEIGHT = 1600

if getattr(sys, 'frozen', False):
    application_path = Path(sys.executable).parent
else:
    application_path = Path(__file__).parent

CONFIG_PATH = application_path / "xhs_xiaodouya_config.json"
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


@dataclass
class Config:
    app_exe: str
    source_dir: Path
    published_dir: Path
    collection_name: str
    account_prefixes: list[str]
    publish_per_account: int
    description_text: str
    publish_delay_sec: float
    upload_wait_sec: float
    single_account_mode: bool
    single_account: str


def load_config() -> Config:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return Config(
        app_exe=data.get("app_exe", DEFAULT_APP_EXE),
        source_dir=Path(data["source_dir"]),
        published_dir=Path(data["published_dir"]),
        collection_name=data.get("collection_name", "天天麻将小红书"),
        account_prefixes=list(data.get("account_prefixes", [f"H{i:02d}" for i in range(1, 13)])),
        publish_per_account=int(data.get("publish_per_account", 1)),
        description_text=data.get(
            "description_text",
            "进#全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        ),
        publish_delay_sec=float(data.get("publish_delay_sec", 8)),
        upload_wait_sec=float(data.get("upload_wait_sec", 10)),
        single_account_mode=bool(data.get("single_account_mode", False)),
        single_account=str(data.get("single_account", "H01")),
    )


class XiaodouyaXhsPoster:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.desktop_uia = Desktop(backend="uia")
        self.desktop_win32 = Desktop(backend="win32")
        self.window = None
        self._abort_last_state = False
        self._stop_requested = False
        self._hotkey_thread = None
        self.publish_button_clicked = False
        self.publish_confirmed = False
        self.task_plan_path = self.config.source_dir / f"xhs_publish_plan_{time.strftime('%Y%m%d')}.txt"
        self.speaker = win32com.client.Dispatch("SAPI.SpVoice")

    def speak(self, text: str) -> None:
        def _speak_thread():
            try:
                self.speaker.Speak(text)
            except Exception:
                pass
        threading.Thread(target=_speak_thread, daemon=True).start()

    def start_hotkey_listener(self) -> None:
        """注册全局 Ctrl+T，紧急终止。"""
        if self._hotkey_thread and self._hotkey_thread.is_alive():
            return

        def _listener() -> None:
            user32 = ctypes.windll.user32
            HOTKEY_ID = 0x1789
            MOD_CONTROL = 0x0002
            VK_T = 0x54
            WM_HOTKEY = 0x0312

            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL, VK_T):
                return
            try:
                msg = ctypes.wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                        self._stop_requested = True
                        print("\n检测到 Ctrl+T，正在紧急终止...")
                        os._exit(130)
            finally:
                user32.UnregisterHotKey(None, HOTKEY_ID)

        self._hotkey_thread = threading.Thread(target=_listener, daemon=True)
        self._hotkey_thread.start()

    def check_abort(self) -> None:
        """全局中止热键：Ctrl+T（按一次即终止）"""
        if self._stop_requested:
            raise KeyboardInterrupt("检测到 Ctrl+T，中止脚本")
        ctrl_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)  # VK_CONTROL
        t_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x54) & 0x8000)      # T
        state = ctrl_down and t_down
        if state and (not self._abort_last_state):
            raise KeyboardInterrupt("检测到 Ctrl+T，中止脚本")
        self._abort_last_state = state

    def run(self) -> None:
        self.start_hotkey_listener()
        self.validate_environment()
        self.ensure_app_window()
        tasks = self.build_tasks()
        if not tasks:
            msg = "没有可执行的发布任务。"
            print(msg)
            self.speak(msg)
            return

        self.speak(f"开始执行小红书发布，共计 {len(tasks)} 个视频")

        for task_index, account_prefix, video_path in tasks:
            self.check_abort()
            if self.is_task_done(task_index):
                print(f"跳过已完成任务：{task_index:03d}. {account_prefix} -> {video_path.name} (down)")
                print("-" * 50)
                continue
            print(f"开始发布：账号={account_prefix} 视频={video_path.name}")
            self.publish_button_clicked = False
            self.publish_confirmed = False
            try:
                self.publish_one(account_prefix, video_path)
                self.mark_task_done(task_index)
                self.move_to_published(video_path)
                print(f"发布完成：{account_prefix} -> {video_path.name}")
            except Exception as exc:
                if self.publish_confirmed:
                    self.mark_task_done(task_index)
                    self.move_to_published(video_path)
                    print(f"[{account_prefix}] 已确认发布成功：{video_path.name}")
                    print("-" * 50)
                    continue
                self.append_error_log(account_prefix, video_path, exc)
                print(f"发布失败：{account_prefix} -> {video_path.name}，原因：{exc}")
            print("-" * 50)
            
        self.speak("所有小红书视频已处理完毕")

    def validate_environment(self) -> None:
        self.config.published_dir.mkdir(parents=True, exist_ok=True)
        if not self.config.source_dir.exists():
            raise RuntimeError(f"视频目录不存在：{self.config.source_dir}")

    def build_tasks(self) -> list[tuple[int, str, Path]]:
        files = [
            p
            for p in self.config.source_dir.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        ]

        accounts = self.config.account_prefixes
        if self.config.single_account_mode:
            accounts = [self.config.single_account]
        if not accounts:
            raise RuntimeError("未配置可用小红书账号。")
        
        # 统一按文件名排序，不再随机
        files = sorted(files, key=lambda x: x.name.lower())

        # 清单条数=当前素材目录的视频条数，有几条就生成几条
        selected = files
        for p in selected:
            # 预先确认绝对路径可用，避免打开文件框后才发现路径问题
            if not p.exists():
                raise RuntimeError(f"待发布文件不存在：{p}")

        tasks: list[tuple[int, str, Path]] = []
        for idx, video_path in enumerate(selected, start=1):
            account = accounts[(idx - 1) % len(accounts)]
            tasks.append((idx, account, video_path))

        done_video_names = self.read_done_video_names_from_plan()
        self.write_task_plan(tasks, done_video_names)
        return tasks

    def read_done_video_names_from_plan(self) -> set[str]:
        if not self.task_plan_path.exists():
            return set()
        done: set[str] = set()
        for line in self.task_plan_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw.endswith(" down"):
                continue
            match = re.match(r"^\d+\.\s+\S+\s+->\s+(.+?)\s+down$", raw)
            if match:
                done.add(match.group(1).strip())
        return done

    def write_task_plan(self, tasks: list[tuple[int, str, Path]], done_video_names: set[str] | None = None) -> None:
        done_video_names = done_video_names or set()
        lines = []
        for task_index, account, video_path in tasks:
            line = f"{task_index:03d}. {account} -> {video_path.name}"
            if video_path.name in done_video_names:
                line += " down"
            lines.append(line)
        content = "\n".join(lines) + ("\n" if lines else "")
        candidates = [
            self.task_plan_path,
            self.config.source_dir / f"xhs_publish_plan_{time.strftime('%Y%m%d')}_run{time.strftime('%H%M%S')}.txt",
            application_path / f"xhs_publish_plan_{time.strftime('%Y%m%d')}_run{time.strftime('%H%M%S')}.txt",
        ]
        last_error = None
        for candidate in candidates:
            try:
                candidate.write_text(content, encoding="utf-8")
                self.task_plan_path = candidate
                print(f"已生成发布清单：{self.task_plan_path}")
                return
            except PermissionError as exc:
                last_error = exc
                continue
        self.task_plan_path = None
        print(f"警告：清单文件写入失败（{last_error}），本次继续发布但不会记录 down 标记。")

    def mark_task_done(self, task_index: int) -> None:
        if not self.task_plan_path:
            return
        if not self.task_plan_path.exists():
            return
        lines = self.task_plan_path.read_text(encoding="utf-8").splitlines()
        prefix = f"{task_index:03d}. "
        for idx, line in enumerate(lines):
            if line.startswith(prefix):
                if not line.endswith(" down"):
                    lines[idx] = line + " down"
                break
        self.task_plan_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def is_task_done(self, task_index: int) -> bool:
        if not self.task_plan_path:
            return False
        if not self.task_plan_path.exists():
            return False
        prefix = f"{task_index:03d}. "
        for line in self.task_plan_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                return line.strip().endswith(" down")
        return False

    def wait_upload_ready(self, video_path: Path, timeout: float = 45.0) -> None:
        """确保已经真正完成视频选择，避免文件框未处理完就进入下一步。"""
        end_at = time.time() + timeout
        hit_count = 0
        keywords = (
            "重新上传",
            "更换视频",
            "封面",
            "裁剪",
            "发布设置",
            "定时发布",
        )
        while time.time() < end_at:
            self.check_abort()
            # 文件框仍在，绝不继续
            if self.wait_open_dialog(timeout=0.2):
                time.sleep(0.3)
                continue

            names = []
            try:
                for c in self.descendants():
                    n = (c.element_info.name or "").strip()
                    if n:
                        names.append(n)
            except Exception:
                time.sleep(0.4)
                continue

            # 命中任一“上传完成后才会稳定出现”的关键词，连续命中2次再放行
            matched = any(any(k in n for k in keywords) for n in names)
            if matched:
                hit_count += 1
            else:
                hit_count = 0

            # 文件名（或去后缀）若出现在页面上也作为上传成功信号
            stem = video_path.stem
            if any((video_path.name in n) or (stem and stem in n) for n in names):
                hit_count += 1

            if hit_count >= 2:
                return
            time.sleep(0.4)

        raise RuntimeError("视频未进入可发布状态（文件可能未真正选中/上传未完成）")

    def ensure_app_window(self) -> None:
        hwnd = win32gui.FindWindow(None, APP_TITLE)
        if not hwnd:
            raise RuntimeError(f"未找到 {APP_TITLE} 窗口，请先打开并登录小豆芽。")
        self.position_app_window(hwnd)
        time.sleep(1)
        self.window = self.desktop_uia.window(handle=hwnd)
        self.window.wait("ready", timeout=10)

    def position_app_window(self, hwnd: int) -> None:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            WINDOW_X,
            WINDOW_Y,
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            0,
        )
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # 某些时机系统会拒绝前置，不阻断流程
            pass
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_NOTOPMOST,
            WINDOW_X,
            WINDOW_Y,
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            0,
        )

    def refresh_window(self) -> None:
        hwnd = win32gui.FindWindow(None, APP_TITLE)
        if hwnd:
            try:
                self.position_app_window(hwnd)
            except Exception:
                pass
            self.window = self.desktop_uia.window(handle=hwnd)
        else:
            self.window = self.desktop_uia.window(title=APP_TITLE)

    def descendants(self, control_type: str | None = None):
        self.check_abort()
        return self.window.descendants(control_type=control_type)

    def safe_click_blank_area(self) -> None:
        safe_x, safe_y = 80, 520
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            if name == "任务市场" and info.rectangle.bottom > 0:
                safe_x = (info.rectangle.left + info.rectangle.right) // 2
                safe_y = info.rectangle.bottom + 30
                break
        mouse.click(button="left", coords=(safe_x, safe_y))
        time.sleep(1)

    def clear_onboarding_popups(self) -> None:
        for _ in range(2):
            self.check_abort()
            for control in self.descendants(control_type="Button"):
                name = (control.element_info.name or "").strip()
                if name in {"我知道了", "知道了", "关闭", "确定", "稍后", "跳过"}:
                    rect = control.element_info.rectangle
                    if rect.right > 0 and rect.bottom > 0:
                        mouse.click(
                            button="left",
                            coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                        )
                        time.sleep(0.6)

    def click_text(self, candidates: list[str], exact: bool = True, retry: int = 2) -> None:
        target = None
        for _ in range(retry):
            self.check_abort()
            self.clear_onboarding_popups()
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                if not name:
                    continue
                matched = name in candidates if exact else any(c in name for c in candidates)
                if matched and info.rectangle.right > 0 and info.rectangle.bottom > 0:
                    target = control
                    break
            if target:
                rect = target.element_info.rectangle
                mouse.click(
                    button="left",
                    coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                )
                time.sleep(0.6)
                return
            time.sleep(0.5)
        raise RuntimeError(f"未找到文本入口：{candidates}")

    def find_account_rect(self, prefix: str):
        for control in self.window.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if not re.match(rf"^{re.escape(prefix)}(?!\d)", name):
                continue
            if info.control_type not in ("Text", "ListItem", "Button", "TreeItem"):
                continue
            if 180 < rect.left < 560 and rect.top > 180 and rect.bottom > rect.top:
                return rect
        return None

    def visible_collection_accounts_ready(self) -> bool:
        expected = [self.config.single_account] if self.config.single_account_mode else self.config.account_prefixes
        for control in self.window.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if info.control_type not in ("Text", "ListItem", "Button", "TreeItem"):
                continue
            if not (180 < rect.left < 560 and rect.top > 180 and rect.bottom > rect.top):
                continue
            if any(re.match(rf"^{re.escape(prefix)}(?!\d)", name) for prefix in expected):
                return True
        return False

    def ensure_collection_expanded(self) -> None:
        self.refresh_window()
        if self.visible_collection_accounts_ready():
            return

        target_rect = None
        for control in self.window.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if info.control_type not in ("Text", "ListItem", "TreeItem"):
                continue
            if self.config.collection_name in name and 180 < rect.left < 560 and rect.top > 150 and rect.bottom > rect.top:
                target_rect = rect
                break

        if not target_rect:
            raise RuntimeError(f"未找到账号合集：{self.config.collection_name}")

        for _ in range(2):
            if self.visible_collection_accounts_ready():
                return
            mouse.click(
                button="left",
                coords=((target_rect.left + target_rect.right) // 2, (target_rect.top + target_rect.bottom) // 2),
            )
            time.sleep(0.8)
            self.refresh_window()

    def click_account(self, prefix: str) -> None:
        self.refresh_window()
        self.ensure_collection_expanded()

        target_rect = self.find_account_rect(prefix)
        if not target_rect:
            for _ in range(6):
                mouse.scroll(coords=(350, 720), wheel_dist=8)
                time.sleep(0.15)
            self.refresh_window()
            self.ensure_collection_expanded()
            target_rect = self.find_account_rect(prefix)

        if not target_rect:
            for _ in range(15):
                self.check_abort()
                self.clear_onboarding_popups()
                mouse.scroll(coords=(350, 860), wheel_dist=-8)
                time.sleep(0.4)
                self.refresh_window()
                target_rect = self.find_account_rect(prefix)
                if target_rect:
                    break

        if not target_rect:
            raise RuntimeError(f"未找到账号：{prefix}")

        center = ((target_rect.left + target_rect.right) // 2, (target_rect.top + target_rect.bottom) // 2)
        mouse.click(button="left", coords=center)
        time.sleep(0.4)
        mouse.click(button="left", coords=center)
        time.sleep(0.8)
        self.safe_click_blank_area()
        time.sleep(1.0)

    def click_publish_note(self) -> None:
        # 已在发布页则直接返回，避免反复找入口导致误报
        if self.is_on_publish_page():
            return

        # 主页左上角入口文案存在差异，按优先级逐个兜底
        for candidates in (
            ["发布笔记"],
            ["发布图文", "发布作品", "去发布"],
            ["发布"],
        ):
            try:
                self.click_text(candidates, exact=False, retry=2)
                time.sleep(0.8)
                if self.is_on_publish_page():
                    return
            except Exception:
                continue
        raise RuntimeError("未找到‘发布笔记/发布作品’入口。")

    def is_on_publish_page(self) -> bool:
        self.refresh_window()
        keywords = (
            "拖拽视频到此",
            "点击上传",
            "上传视频",
            "输入正文描述",
            "填写标题",
        )
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if rect.right <= 0 or rect.bottom <= 0:
                continue
            if any(k in name for k in keywords):
                return True
        return False

    def click_upload_video(self) -> None:
        # 先按锚点按钮打开，失败后再用“上传视频/点击上传”文本兜底，降低 UI 漂移影响
        last_err = None
        try:
            self.open_upload_dialog()
            return
        except Exception as e:
            last_err = e
            print(f"open_upload_dialog failed: {e}")

        for candidates in (["上传视频"], ["点击上传"]):
            try:
                self.click_text(candidates, exact=False, retry=1)
                if self.wait_open_dialog(timeout=2.5):
                    return
                print(f"文本点击兜底：已点击 {candidates}，但未检测到对话框")
            except Exception as e:
                print(f"文本点击兜底失败：{candidates} - {e}")
                continue

        raise RuntimeError(f"未能打开上传对话框（锚点点击与文本兜底均失败）。open_upload_dialog error: {last_err}")

    def wait_open_dialog(self, timeout: float = 3.0):
        end_at = time.time() + timeout
        while time.time() < end_at:
            self.check_abort()
            for title in ("打开", "Open"):
                try:
                    dialog = self.desktop_win32.window(title=title)
                    if not dialog.exists(timeout=0.2):
                        continue
                    handle = dialog.wrapper_object().handle
                    if not win32gui.IsWindow(handle):
                        continue
                    if not win32gui.IsWindowVisible(handle):
                        continue
                    return dialog
                except Exception:
                    continue
            time.sleep(0.2)
        return None

    def walk_child_windows(self, parent_hwnd: int) -> list[int]:
        result: list[int] = []

        def _walk(hwnd: int) -> None:
            child = win32gui.FindWindowEx(hwnd, 0, None, None)
            while child:
                result.append(child)
                _walk(child)
                child = win32gui.FindWindowEx(hwnd, child, None, None)

        _walk(parent_hwnd)
        return result

    def dump_open_dialog_controls(self, dialog_handle: int) -> None:
        try:
            lines = [f"[dialog dump] handle={dialog_handle}"]
            for hwnd in self.walk_child_windows(dialog_handle):
                try:
                    cls = win32gui.GetClassName(hwnd)
                    text = win32gui.GetWindowText(hwnd)
                    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                    visible = win32gui.IsWindowVisible(hwnd)
                    enabled = win32gui.IsWindowEnabled(hwnd)
                    lines.append(
                        f"hwnd={hwnd} class={cls} text={text!r} rect=({left},{top},{right},{bottom}) visible={visible} enabled={enabled}"
                    )
                except Exception as exc:
                    lines.append(f"hwnd={hwnd} dump_error={exc}")
            with open("xhs_open_dialog_dump.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass

    def find_open_dialog_filename_edit(self, dialog_handle: int) -> int | None:
        candidates: list[tuple[int, int, int, int]] = []
        for hwnd in self.walk_child_windows(dialog_handle):
            try:
                if win32gui.GetClassName(hwnd) != "Edit":
                    continue
                if not win32gui.IsWindowVisible(hwnd):
                    continue
                if not win32gui.IsWindowEnabled(hwnd):
                    continue
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width = right - left
                height = bottom - top
                if width < 120 or height <= 0:
                    continue
                candidates.append((hwnd, top, width, bottom))
            except Exception:
                continue

        if not candidates:
            return None

        # 底部区域、宽度较大的一般就是“文件名(N)”输入框
        candidates.sort(key=lambda x: (x[1], x[2], x[3]))
        return candidates[-1][0]

    def find_open_dialog_confirm_button(self, dialog_handle: int) -> int | None:
        candidates: list[tuple[int, int, int]] = []
        for hwnd in self.walk_child_windows(dialog_handle):
            try:
                if win32gui.GetClassName(hwnd) != "Button":
                    continue
                if not win32gui.IsWindowVisible(hwnd):
                    continue
                text = (win32gui.GetWindowText(hwnd) or "").strip()
                if not any(k in text for k in ("打开", "确定")):
                    continue
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                candidates.append((hwnd, left, top))
            except Exception:
                continue

        if not candidates:
            return None

        # 通常“打开”按钮位于底部偏右
        candidates.sort(key=lambda x: (x[2], x[1]))
        return candidates[-1][0]

    def set_native_edit_text(self, edit_hwnd: int, text: str) -> None:
        win32gui.SendMessage(edit_hwnd, win32con.WM_SETTEXT, 0, text)
        time.sleep(0.2)

    def click_native_button(self, button_hwnd: int) -> None:
        BM_CLICK = getattr(win32con, "BM_CLICK", 245)
        win32gui.SendMessage(button_hwnd, BM_CLICK, 0, 0)
        time.sleep(0.3)

    def open_upload_dialog(self) -> None:
        # 方案0：直接命中上传按钮文本，优先处理部分页面无锚点文案的情况
        for _ in range(2):
            self.check_abort()
            for btn in self.descendants():
                try:
                    info = btn.element_info
                    name = (info.name or "").strip()
                    rect = info.rectangle
                    if rect.right <= 0 or rect.bottom <= 0:
                        continue
                    if not any(k in name for k in ("上传视频", "点击上传")):
                        continue
                    if "图文" in name:
                        continue
                    if info.control_type not in ("Button", "Text", "Image", "Pane", "Group"):
                        continue
                    # 过滤侧边栏/顶部小按钮，只点中间内容区的上传入口
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    if not (420 <= cx <= 2280 and 180 <= cy <= 1400):
                        continue
                    try:
                        btn.click_input()
                    except Exception:
                        try:
                            btn.invoke()
                        except Exception:
                            continue
                    time.sleep(0.45)
                    if self.wait_open_dialog(timeout=1.8):
                        return
                except Exception:
                    continue

        # 方案1：按“拖拽视频到此或点击上传”锚点定位，点击其下方红色按钮区域
        for _ in range(3):
            self.check_abort()
            anchor = None
            anchor_control = None
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                rect = info.rectangle
                if ("拖拽视频到此" in name or "点击上传" in name) and rect.right > 0 and rect.bottom > 0:
                    anchor = rect
                    anchor_control = control
                    break

            if anchor:
                # 优先找锚点下方最近按钮，避免乱点与慢搜索
                nearest_btn = None
                nearest_dist = 10**9
                cx = (anchor.left + anchor.right) // 2
                for btn in self.descendants(control_type="Button"):
                    bi = btn.element_info
                    br = bi.rectangle
                    if br.right <= 0 or br.bottom <= 0:
                        continue
                    if br.top < anchor.bottom:
                        continue
                    dist_y = br.top - anchor.bottom
                    if dist_y > 260:
                        continue
                    bcx = (br.left + br.right) // 2
                    if abs(bcx - cx) > 260:
                        continue
                    if dist_y < nearest_dist:
                        nearest_dist = dist_y
                        nearest_btn = btn

                if nearest_btn:
                    try:
                        nearest_btn.click_input()
                    except Exception:
                        try:
                            nearest_btn.invoke()
                        except Exception:
                            pass
                    time.sleep(0.5)
                    if self.wait_open_dialog(timeout=2.0):
                        return

                # 再回退到相对坐标点击（只在锚点附近）
                for dy in (36, 52, 68):
                    try:
                        mouse.click(button="left", coords=(cx, anchor.bottom + dy))
                    except Exception:
                        if anchor_control:
                            try:
                                anchor_control.click_input(coords=(0, dy + 10))
                            except Exception:
                                pass
                    time.sleep(0.35)
                    if self.wait_open_dialog(timeout=1.2):
                        return

        # 方案2：仅做一次“上传视频”文本点击兜底（避免到处找）
        self.click_text(["上传视频"], exact=False, retry=1)
        if self.wait_open_dialog(timeout=2.5):
            return

        raise RuntimeError("未能成功打开文件选择框：未点中‘拖拽视频到此或点击上传’下方红色按钮")

    def upload_file(self, video_path: Path) -> None:
        dialog = self.wait_open_dialog(timeout=20)
        if not dialog:
            raise RuntimeError("未检测到“打开”文件选择框")
        if not video_path.exists():
            raise RuntimeError(f"视频文件不存在：{video_path}")
        full_path = str(video_path.resolve())
        # 完全复用抖音脚本已验证过的稳定思路：
        # “打开”对话框 -> class_name=Edit, found_index=0 -> 绝对路径注入 -> 回车确认
        try:
            try:
                dialog.wait("ready", timeout=10)
            except Exception:
                # 某些系统文件框 ready 状态不稳定，但控件仍可直接操作
                pass

            handle = dialog.wrapper_object().handle
            file_name_edit = dialog.child_window(class_name="Edit", found_index=0)
            try:
                win32gui.SetForegroundWindow(handle)
            except Exception:
                pass
            time.sleep(0.5)
            file_name_edit.set_edit_text(full_path)
            time.sleep(0.5)
            keyboard.send_keys("{ENTER}")
            dialog.wait_not("visible", timeout=30)
            time.sleep(self.config.upload_wait_sec)
            if self.wait_open_dialog(timeout=0.8):
                raise RuntimeError("文件选择框未正常关闭，视频可能未成功选择")
            self.wait_upload_ready(video_path, timeout=max(30.0, self.config.upload_wait_sec + 25.0))
            return
        except Exception as exc:
            try:
                self.dump_open_dialog_controls(dialog.wrapper_object().handle)
            except Exception:
                pass
            raise RuntimeError(f"按抖音同款绝对路径注入方式选视频失败：{exc}") from exc

    @staticmethod
    def paste_text(text: str) -> None:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        keyboard.send_keys("^a{BACKSPACE}")
        time.sleep(0.2)
        keyboard.send_keys("^v")
        time.sleep(0.5)

    def click_named_input_area(self, keywords: tuple[str, ...], retry: int = 2):
        """优先按占位文案点击输入区域，而不是死盯 Edit 控件。"""
        for _ in range(retry):
            self.check_abort()
            self.clear_onboarding_popups()

            # 先找带占位文案的控件本身
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                rect = info.rectangle
                if rect.right <= 0 or rect.bottom <= 0:
                    continue
                if any(k in name for k in keywords):
                    mouse.click(
                        button="left",
                        coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                    )
                    time.sleep(0.2)
                    return control

            # 再退回找 Edit：有些输入框本体无文案，但附近会有占位描述
            edit_candidates = []
            for control in self.descendants(control_type="Edit"):
                info = control.element_info
                rect = info.rectangle
                if rect.right > 0 and rect.bottom > 0:
                    edit_candidates.append(control)
            if edit_candidates:
                # 小红书标题/正文一般在右侧主区域，优先最后出现且位置更靠右/靠下的编辑区
                edit_candidates.sort(
                    key=lambda c: (
                        c.element_info.rectangle.top,
                        c.element_info.rectangle.left,
                        c.element_info.rectangle.bottom,
                    )
                )
                target = edit_candidates[-1]
                rect = target.element_info.rectangle
                mouse.click(
                    button="left",
                    coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                )
                time.sleep(0.2)
                return target

            time.sleep(0.5)

        raise RuntimeError(f"未找到输入区域：{keywords}")

    def fill_title_and_description(self, video_path: Path) -> None:
        self.clear_onboarding_popups()

        # 标题：用视频文件名填写标题
        self.click_named_input_area(("填写标题", "会有很多赞", "作品标题"), retry=3)
        self.paste_text(video_path.stem)
        time.sleep(0.3)

        # 正文（固定话题词）：填写内容并打空格让话题高亮
        self.click_named_input_area(("输入正文描述", "添加正文描述", "正文描述", "正文"), retry=3)
        self.paste_text(self.config.description_text)
        time.sleep(0.3)
        keyboard.send_keys(" ")
        time.sleep(0.2)
        keyboard.send_keys("{ENTER}")
        time.sleep(0.3)

    def scroll_to_bottom(self) -> None:
        mouse.scroll(coords=(1600, 1200), wheel_dist=-8)
        time.sleep(0.3)
        mouse.scroll(coords=(1600, 1200), wheel_dist=-8)
        time.sleep(0.3)
        mouse.scroll(coords=(1600, 1200), wheel_dist=-8)
        time.sleep(0.4)

    def find_publish_button(self):
        self.clear_onboarding_popups()
        target = None
        max_top = -1
        for btn in self.descendants(control_type="Button"):
            info = btn.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if name == "发布" and rect.right > 0 and rect.bottom > 0:
                if rect.top > max_top:
                    target = btn
                    max_top = rect.top

        return target

    def is_publish_editor_active(self) -> bool:
        self.refresh_window()
        title_keywords = ("填写标题", "会有很多赞", "作品标题")
        desc_keywords = ("输入正文描述", "添加正文描述", "正文描述", "正文")
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if rect.right <= 0 or rect.bottom <= 0:
                continue
            if any(k in name for k in title_keywords):
                return True
            if any(k in name for k in desc_keywords):
                return True
        return self.find_publish_button() is not None

    def wait_for_publish_page_change(self, timeout: float = 3.0) -> bool:
        end_at = time.time() + timeout
        while time.time() < end_at:
            self.check_abort()
            self.clear_onboarding_popups()
            if not self.is_publish_editor_active():
                return True
            time.sleep(0.3)
        return False

    def click_final_publish(self) -> None:
        self.clear_onboarding_popups()
        max_attempts = 8
        for attempt in range(max_attempts):
            target = self.find_publish_button()
            if not target:
                self.publish_confirmed = True
                time.sleep(self.config.publish_delay_sec)
                return

            rect = target.element_info.rectangle
            mouse.click(
                button="left",
                coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
            )
            self.publish_button_clicked = True

            if self.wait_for_publish_page_change(timeout=3.0):
                self.publish_confirmed = True
                time.sleep(self.config.publish_delay_sec)
                return

            print(f"发布点击后页面无变化，3秒后重试 ({attempt + 1}/{max_attempts})")

        raise RuntimeError("点击发布后页面始终无变化，可能视频仍未上传完成。")

    def publish_one(self, account_prefix: str, video_path: Path) -> None:
        self.check_abort()
        self.click_text(["多开面板"], exact=False, retry=2)
        self.ensure_collection_expanded()
        self.click_account(account_prefix)
        self.click_publish_note()
        self.click_upload_video()
        self.upload_file(video_path)
        self.fill_title_and_description(video_path)
        self.scroll_to_bottom()
        self.click_final_publish()

    def move_to_published(self, video_path: Path) -> None:
        import os

        dst = self.config.published_dir / video_path.name
        self.config.published_dir.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            try:
                if dst.exists():
                    dst.unlink()
                shutil.move(str(video_path), str(dst))
                print(f"已移动到：{dst}")
                return
            except PermissionError:
                print(f"文件占用，1秒后重试({i + 1}/2)：{video_path.name}")
                time.sleep(1)

        os.system(f'move /Y "{video_path}" "{dst}" >nul 2>&1')
        if video_path.exists():
            print(f"视频移动失败（被占用），已在清单标记down，不影响后续跳过：{video_path}")

    @staticmethod
    def append_error_log(account: str, video_path: Path, exc: Exception) -> None:
        import traceback

        with open("xhs_error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{account}] 处理 {video_path.name} 出错：\n")
            traceback.print_exc(file=f)


def main() -> int:
    try:
        cfg = load_config()
        XiaodouyaXhsPoster(cfg).run()
        return 0
    except KeyboardInterrupt as exc:
        print(f"\n已终止：{exc}")
        return 130
    except Exception as exc:
        import traceback

        with open("xhs_error_log.txt", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"执行失败：{exc}，详情见 xhs_error_log.txt", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
