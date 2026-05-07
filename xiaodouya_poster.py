import json
import os
import shutil
import sys
import time
import ctypes
import threading
from dataclasses import dataclass
from itertools import cycle, islice
from pathlib import Path
from typing import Optional

import win32con
import win32clipboard
import win32gui
import win32com.client
from pywinauto import Desktop, keyboard, mouse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def safe_console_text(text: object) -> str:
    s = str(text)
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        s.encode(enc)
        return s
    except Exception:
        return s.encode(enc, errors="replace").decode(enc, errors="replace")


APP_EXE = r"C:\Program Files\xiaodouya\新榜小豆芽.exe"
APP_TITLE = "新榜小豆芽"
UPLOAD_EDIT_PLACEHOLDER = "填写作品标题，为作品获得更多流量"
WINDOW_X = 50
WINDOW_Y = 50
WINDOW_WIDTH = 2560
WINDOW_HEIGHT = 1600
INITIAL_WINDOW_WAIT_SEC = 0.6
WINDOW_READY_TIMEOUT_SEC = 3

if getattr(sys, 'frozen', False):
    # If the application is run as a bundle, the PyInstaller bootloader
    # extends the sys module by a flag frozen=True and sets the app 
    # path into variable _MEIPASS'.
    application_path = Path(sys.executable).parent
else:
    application_path = Path(__file__).parent

DEFAULT_CONFIG_PATH = application_path / "xiaodouya_config.json"
PUBLISHED_HISTORY_PATH = application_path / "published_history.txt"


@dataclass
class Config:
    source_dir: Path
    published_dir: Path
    app_exe: str
    account_prefixes: list[str]
    task_title: str
    hashtags: list[str]
    single_run: bool
    publish_delay_sec: float


def load_config() -> Config:
    config_path = Path(os.environ.get("XIAODOUYA_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)))
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return Config(
        source_dir=Path(data["source_dir"]),
        published_dir=Path(data["published_dir"]),
        app_exe=data.get("app_exe", APP_EXE),
        account_prefixes=list(data.get("account_prefixes", ["01号"])),
        task_title=data["task_title"],
        hashtags=list(
            data.get(
                "hashtags",
                [
                    "#疯少的时代",
                    "#百日破冰征程",
                    "#狮心会点燃三国冰河时代",
                ],
            )
        ),
        single_run=bool(data.get("single_run", True)),
        publish_delay_sec=float(data.get("publish_delay_sec", 6)),
    )


class XiaodouyaPoster:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.desktop_uia = Desktop(backend="uia")
        self.desktop_win32 = Desktop(backend="win32")
        self.window = None
        self._abort_last_state = False
        self._stop_requested = False
        self._hotkey_thread = None
        self.publish_button_clicked = False
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
        self.ensure_app_window()
        self.sync_already_published_files()
        videos = self.list_videos()
        pending_moves: list[Path] = []
        if not videos:
            msg = "未找到待发布视频。"
            print(msg)
            self.speak(msg)
            return

        self.speak(f"开始执行抖音发布，共计 {len(videos)} 个视频")
        assignments = self.build_assignments(videos)
        for account_prefix, video in assignments:
            self.check_abort()
            print(f"开始处理账号 {account_prefix}，视频 {safe_console_text(video.name)}")
            self.publish_button_clicked = False
            try:
                self.publish_one(account_prefix, video)
                if not self.move_to_published(video, max_retries=1, retry_wait_sec=1):
                    pending_moves.append(video)
            except Exception as e:
                if self.publish_button_clicked:
                    print(f"[{account_prefix}] 已点击红色发布按钮，按成功处理：{safe_console_text(video.name)}")
                    if not self.move_to_published(video, max_retries=1, retry_wait_sec=1):
                        pending_moves.append(video)
                    print("-" * 40)
                    continue
                import traceback
                with open("error_log.txt", "a", encoding="utf-8") as f:
                    f.write(f"\n[{account_prefix}] 处理 {video.name} 时出错:\n")
                    traceback.print_exc(file=f)
                msg = f"[{account_prefix}] 发布失败：{e}。脚本遇到错误，停止运行。"
                print(msg)
                self.speak(msg)
                raise  # 将异常抛出以停止脚本运行
            print("-" * 40)

        self.retry_pending_moves(pending_moves)
        self.speak("所有抖音视频已处理完毕")

    def build_assignments(self, videos: list[Path]) -> list[tuple[str, Path]]:
        accounts = self.config.account_prefixes
        if not accounts:
            raise RuntimeError("配置中没有可用账号。")

        if self.config.single_run:
            selected_accounts = accounts[: len(videos)]
        else:
            selected_accounts = list(islice(cycle(accounts), len(videos)))

        return list(zip(selected_accounts, videos))

    def list_videos(self) -> list[Path]:
        self.config.published_dir.mkdir(parents=True, exist_ok=True)
        already_published = self.get_published_names()
        pending: list[Path] = []
        for p in self.config.source_dir.iterdir():
            if not p.is_file() or p.suffix.lower() not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
                continue
            if p.name in already_published:
                # 已经发布过的同名文件直接从待发布目录清理，避免重复上传
                try:
                    p.unlink()
                    print(f"已剔除重复待发布文件：{safe_console_text(p.name)}")
                except Exception:
                    pass
                continue
            pending.append(p)
        return sorted(pending, key=lambda p: p.name)

    def get_published_names(self) -> set[str]:
        names: set[str] = set()
        if self.config.published_dir.exists():
            for p in self.config.published_dir.iterdir():
                if p.is_file():
                    names.add(p.name)
        if PUBLISHED_HISTORY_PATH.exists():
            for line in PUBLISHED_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    names.add(parts[2].strip())
        return names

    def record_published(self, account_prefix: str, video_name: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with PUBLISHED_HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts}|{account_prefix}|{video_name}\n")

    def sync_already_published_files(self) -> None:
        """脚本启动前做一次去重同步，确保不会把已发布视频再次上传。"""
        self.config.published_dir.mkdir(parents=True, exist_ok=True)
        published_names = self.get_published_names()
        if not published_names:
            return
        for p in self.config.source_dir.iterdir():
            if not p.is_file() or p.suffix.lower() not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
                continue
            if p.name in published_names:
                try:
                    p.unlink()
                    print(f"启动去重：已剔除 {safe_console_text(p.name)}")
                except Exception:
                    pass

    def ensure_app_window(self) -> None:
        hwnd = win32gui.FindWindow(None, APP_TITLE)
        if not hwnd:
            raise RuntimeError(f"未找到 {APP_TITLE} 窗口，请先打开软件并登录账号。")

        self.position_app_window(hwnd)
        time.sleep(INITIAL_WINDOW_WAIT_SEC)
        self.window = self.desktop_uia.window(handle=hwnd)
        self.window.wait("ready", timeout=WINDOW_READY_TIMEOUT_SEC)

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
        try:
            hwnd = win32gui.FindWindow(None, APP_TITLE)
            if hwnd:
                self.position_app_window(hwnd)
                self.window = self.desktop_uia.window(handle=hwnd)
        except Exception:
            pass

    def descendants(self, control_type: Optional[str] = None):
        self.check_abort()
        if control_type:
            return self.window.descendants(control_type=control_type)
        else:
            return self.window.descendants()

    def is_publish_editor_page(self) -> bool:
        """通过标题框/发布区特征判断是否已经进入抖音作品编辑页。"""
        self.refresh_window()
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if name == UPLOAD_EDIT_PLACEHOLDER and rect.left > 1100 and rect.bottom > rect.top:
                return True
            if name in {"作品描述", "设置封面", "发布设置", "#添加话题"} and rect.left > 1500:
                return True
        return False

    def wait_publish_editor_ready(self, timeout: float = 40.0) -> None:
        end_at = time.time() + timeout
        while time.time() < end_at:
            if self.is_publish_editor_page():
                return
            time.sleep(1.0)
        raise RuntimeError("视频上传后未进入作品编辑页。")

    def has_open_file_dialog(self) -> bool:
        for title in ("打开", "Open"):
            try:
                dialog = self.desktop_win32.window(title=title)
                if dialog.exists(timeout=0.2):
                    return True
            except Exception:
                continue
        return False

    def wait_open_dialog(self, timeout: float = 8.0):
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

    def normalize_task_page_scroll_top(self) -> None:
        for _ in range(6):
            mouse.scroll(coords=(1600, 900), wheel_dist=8)
            time.sleep(0.15)

    def wait_task_detail_ready(self, timeout: float = 20.0) -> str:
        """等待任务详情页就绪，返回 task_detail/editor/dialog 三种状态。"""
        end_at = time.time() + timeout
        upload_keywords = ("上传视频", "点击上传", "拖拽视频")
        while time.time() < end_at:
            if self.has_open_file_dialog():
                return "dialog"
            if self.is_publish_editor_page():
                return "editor"

            self.refresh_window()
            try:
                for control in self.descendants():
                    info = control.element_info
                    name = (info.name or "").strip()
                    rect = info.rectangle
                    if rect.bottom <= rect.top or rect.right <= rect.left:
                        continue
                    if any(keyword in name for keyword in upload_keywords):
                        return "task_detail"
            except Exception:
                pass
            time.sleep(1.0)
        raise RuntimeError("点击“查看详情”后未进入可上传页面。")

    def find_account_rect(self, prefix: str):
        for control in self.window.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            if not name.startswith(prefix):
                continue
            if info.control_type not in ("Text", "TreeItem", "ListItem"):
                continue
            rect = info.rectangle
            if 180 < rect.left < 560 and rect.top > 180 and rect.bottom > rect.top:
                return rect
        return None

    def visible_douyin_accounts_ready(self) -> bool:
        visible_prefixes = set()
        for control in self.window.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if info.control_type not in ("Text", "TreeItem", "ListItem"):
                continue
            if not (180 < rect.left < 560 and rect.top > 180 and rect.bottom > rect.top):
                continue
            for prefix in self.config.account_prefixes:
                if name.startswith(prefix):
                    visible_prefixes.add(prefix)
        # 只要能看到第一个和最后一个账号中的任意一个，或者能看到一定数量的账号，就认为已展开
        if not self.config.account_prefixes:
            return False
        first = self.config.account_prefixes[0]
        last = self.config.account_prefixes[-1]
        return first in visible_prefixes or last in visible_prefixes or len(visible_prefixes) >= 3

    def ensure_douyin_group_expanded(self) -> None:
        self.refresh_window()
        if self.visible_douyin_accounts_ready():
            return

        for _ in range(2):
            group_rect = None
            self.refresh_window()
            for control in self.window.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                rect = info.rectangle
                if rect.left <= 0 or rect.bottom <= rect.top:
                    continue
                if "抖音发布" in name and info.control_type in ("Text", "TreeItem", "ListItem"):
                    group_rect = rect
                    break

            if group_rect:
                mouse.click(
                    button="left",
                    coords=((group_rect.left + group_rect.right) // 2, (group_rect.top + group_rect.bottom) // 2),
                )
                time.sleep(0.5)
                self.refresh_window()
                if self.visible_douyin_accounts_ready():
                    return

    def click_account(self, prefix: str) -> None:
        self.refresh_window()
        self.ensure_douyin_group_expanded()

        target_rect = self.find_account_rect(prefix)
        if not target_rect:
            for _ in range(2):
                mouse.scroll(coords=(350, 700), wheel_dist=8)
                time.sleep(0.15)
            self.refresh_window()
            self.ensure_douyin_group_expanded()
            target_rect = self.find_account_rect(prefix)

        if not target_rect:
            for _ in range(5):
                mouse.scroll(coords=(350, 820), wheel_dist=-6)
                time.sleep(0.35)
                self.refresh_window()
                target_rect = self.find_account_rect(prefix)
                if target_rect:
                    break

        if not target_rect:
            raise RuntimeError(f"未找到账号：{prefix}")
        
        center_x = (target_rect.left + target_rect.right) // 2
        center_y = (target_rect.top + target_rect.bottom) // 2
        
        self.refresh_window()
        # 第一次点击可能会触发悬浮窗
        mouse.click(button="left", coords=(center_x, center_y))
        time.sleep(0.5)
        # 再次点击同一位置进入页面
        mouse.click(button="left", coords=(center_x, center_y))
        time.sleep(0.6)
        
        # 找到左侧菜单的“任务市场”，并在其下方1厘米处点击，消除残留的悬浮资料卡
        safe_click_x, safe_click_y = 50, 500  # 兜底坐标
        self.refresh_window()
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            if name == "任务市场" and info.control_type in ("Text", "ListItem"):
                rect = info.rectangle
                if rect.left > 0 and rect.bottom > 0:
                    safe_click_x = (rect.left + rect.right) // 2
                    safe_click_y = rect.bottom + 30  # 任务市场正下方约 1 厘米处
                    break
        
        mouse.click(button="left", coords=(safe_click_x, safe_click_y))
        time.sleep(1.2)

    def goto_my_task(self) -> None:
        # 在进入账号后，可能需要等待缓冲
        for _ in range(10):
            self.refresh_window()
            target = None
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                if name == "我的任务":
                    rect = info.rectangle
                    if rect.right > 0:
                        target = control
                        break
            if target:
                break
            
            monetize = None
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                if "变现中心" in name:
                    rect = info.rectangle
                    if rect.right > 0 and rect.bottom > 0:
                        monetize = control
                        break
            if monetize:
                break
            time.sleep(1.0)

        # 1. 尝试直接找“我的任务”，如果能找到说明已经展开，直接点
        target = None
        self.refresh_window()
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            if name == "我的任务":
                rect = info.rectangle
                if rect.right > 0:
                    target = control
                    break
        
        # 2. 如果没找到，说明可能折叠在“变现中心”里
        if not target:
            self.refresh_window()
            monetize = None
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                if "变现中心" in name:
                    rect = info.rectangle
                    if rect.right > 0 and rect.bottom > 0:
                        monetize = control
                        break
            
            if monetize:
                rect = monetize.element_info.rectangle
                # 尽量点文字中心，避开右侧小箭头可能造成的误触区域
                mouse.click(button="left", coords=(rect.left + 30, (rect.top+rect.bottom)//2))
                time.sleep(2)
                
                # 展开后再找一次
                for control in self.descendants():
                    info = control.element_info
                    name = (info.name or "").strip()
                    if name == "我的任务":
                        rect = info.rectangle
                        if rect.right > 0:
                            target = control
                            break

        if not target:
            # 可能是停留在投稿等全屏页
            self.refresh_window()
            
            # 直接尝试关闭当前标签页，防止无限叠加
            for _ in range(3):
                closed_any = False
                for control in self.descendants():
                    info = control.element_info
                    name = (info.name or "").strip()
                    if "关闭" in name and info.control_type == "Button":
                        rect = info.rectangle
                        if rect.top > 0 and rect.bottom > 0:
                            mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
                            time.sleep(2)
                            closed_any = True
                            break
                if not closed_any:
                    break
            
            # 再从左侧栏点一次账号进来
            time.sleep(2)
            self.refresh_window()
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                if name.startswith("0") and info.control_type == "Text":
                    rect = info.rectangle
                    if 200 < rect.left < 500 and rect.top > 200:
                        mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
                        time.sleep(2)
                        # 点击“任务市场”下方消除悬浮窗
                        safe_click_x, safe_click_y = 50, 500
                        self.refresh_window()
                        for ctrl in self.descendants():
                            inf = ctrl.element_info
                            if (inf.name or "").strip() == "任务市场" and inf.control_type in ("Text", "ListItem"):
                                if inf.rectangle.left > 0 and inf.rectangle.bottom > 0:
                                    safe_click_x = (inf.rectangle.left + inf.rectangle.right) // 2
                                    safe_click_y = inf.rectangle.bottom + 30
                                    break
                        mouse.click(button="left", coords=(safe_click_x, safe_click_y))
                        time.sleep(2)
                        break
            
            # 再次找变现中心和我的任务
            self.refresh_window()
            for control in self.descendants():
                info = control.element_info
                name = (info.name or "").strip()
                if "变现中心" in name:
                    rect = info.rectangle
                    if rect.right > 0 and rect.bottom > 0:
                        mouse.click(button="left", coords=(rect.left + 30, (rect.top+rect.bottom)//2))
                        time.sleep(2)
                        break
            self.refresh_window()
            for control in self.descendants():
                name = (control.element_info.name or "").strip()
                rect = control.element_info.rectangle
                if name == "我的任务" and rect.right > 0 and rect.bottom > 0:
                    target = control
                    break
        if not target:
            raise RuntimeError("未找到“我的任务”入口。")
        # target.click_input() 会在多个窗口时崩溃，改用精确坐标点击
        rect = target.element_info.rectangle
        mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
        time.sleep(2)

    def click_task_detail(self, task_title: str) -> None:
        target = None
        for _ in range(5):
            self.refresh_window()
            desc = self.descendants()
            for index, control in enumerate(desc):
                name = (control.element_info.name or "").strip()
                if name == task_title:
                    for next_control in desc[index + 1 : index + 25]:
                        next_name = (next_control.element_info.name or "").strip()
                        if next_name == "查看详情":
                            rect = next_control.element_info.rectangle
                            if rect.right > 0 and rect.bottom > 0:
                                target = next_control
                                break
                    if target:
                        break
            if target:
                break
            time.sleep(1.0)
            
        if not target:
            raise RuntimeError(f"未找到任务详情按钮：{task_title}")
        rect = target.element_info.rectangle
        mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
        time.sleep(2)
        self.wait_task_detail_ready(timeout=20.0)

    def click_upload_video_entry(self) -> None:
        """任务详情页里的上传入口，允许 Button / Text / Group 多种控件形态。"""
        if self.is_publish_editor_page():
            print("当前已在作品编辑页，跳过“上传视频”入口点击。")
            return
        if self.has_open_file_dialog():
            print("检测到文件选择框已打开，跳过“上传视频”入口点击。")
            return

        self.normalize_task_page_scroll_top()
        state = self.wait_task_detail_ready(timeout=12.0)
        if state in {"editor", "dialog"}:
            return

        upload_keywords = ("上传视频", "点击上传", "拖拽视频")
        for attempt in range(4):
            self.refresh_window()
            target = None

            # 先精确找真正的上传按钮
            for control in self.descendants(control_type="Button"):
                info = control.element_info
                name = (info.name or "").strip()
                rect = info.rectangle
                if name == "上传视频" and rect.bottom > rect.top and rect.right > rect.left:
                    target = control
                    break

            # 再退回到更宽松的多控件搜索
            if not target:
                for control in self.descendants():
                    info = control.element_info
                    name = (info.name or "").strip()
                    rect = info.rectangle
                    if rect.bottom <= rect.top or rect.right <= rect.left:
                        continue
                    if "图文" in name:
                        continue
                    if info.control_type not in ("Button", "Text", "Group", "Pane", "Hyperlink", "Image"):
                        continue
                    if any(keyword in name for keyword in upload_keywords):
                        target = control
                        break

            if target:
                info = target.element_info
                rect = info.rectangle
                try:
                    target.click_input()
                except Exception:
                    click_x = (rect.left + rect.right) // 2
                    click_y = (rect.top + rect.bottom) // 2
                    mouse.click(button="left", coords=(click_x, click_y))
                time.sleep(1.0)
                if self.wait_open_dialog(timeout=3.0) or self.is_publish_editor_page():
                    return

            # 第一轮先回顶部找，后续再轻微向下滚动，避免一直在错误区域打转
            if attempt == 0:
                self.normalize_task_page_scroll_top()
            else:
                mouse.scroll(coords=(1600, 900), wheel_dist=-4)
            time.sleep(1.0)

        raise RuntimeError("未找到任务详情页里的“上传视频”入口。")

    def click_named_button(self, name: str, min_left: int = 0) -> None:
        target = None
        for _ in range(3):
            self.refresh_window()
            for control in self.descendants(control_type="Button"):
                info = control.element_info
                cname = (info.name or "").strip()
                if cname == name:
                    rect = info.rectangle
                    if rect.right > 0 and rect.left >= min_left:
                        target = control
                        break
            if target:
                break

            time.sleep(2)
            
        if not target:
            raise RuntimeError(f"未找到按钮：{name}")
        target.click_input()
        time.sleep(2)

    def upload_file(self, video_path: Path) -> None:
        print(f"准备上传文件：{safe_console_text(video_path.name)}")
        dialog = self.wait_open_dialog(timeout=20)
        if not dialog:
            raise RuntimeError("未检测到“打开”文件选择框")
        if not video_path.exists():
            raise RuntimeError(f"视频文件不存在：{video_path}")

        try:
            dialog.wait("ready", timeout=10)
        except Exception:
            pass

        file_name_edit = dialog.child_window(class_name="Edit", found_index=0)
        
        # 激活对话框并填入文字
        win32gui.SetForegroundWindow(dialog.wrapper_object().handle)
        time.sleep(0.5)
        file_name_edit.set_edit_text(str(video_path.resolve()))
        time.sleep(0.5)
        
        # 直接用键盘敲回车，代替找按钮点击
        keyboard.send_keys("{ENTER}")
        
        # 等待上传框消失，说明已经进入到了发布详情页
        dialog.wait_not("visible", timeout=30)
        time.sleep(10)

    def clear_onboarding_popups(self) -> None:
        """清除页面上的新手引导弹窗，如'我知道了'等"""
        for _ in range(2):
            self.refresh_window()
            for control in self.descendants(control_type="Button"):
                name = (control.element_info.name or "").strip()
                if name in ("我知道了", "关闭", "确定"):
                    try:
                        rect = control.element_info.rectangle
                        mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
                        time.sleep(1)
                    except Exception:
                        pass

    def set_title_from_filename(self, video_path: Path) -> None:
        self.clear_onboarding_popups()
        title = video_path.stem
        # 不再和标题拼接到同一行
        full_text = title

        def copy_text(text: str) -> None:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
        
        target = None
        for _ in range(3):
            self.refresh_window()
            for control in self.descendants():
                name = (control.element_info.name or "").strip()
                rect = control.element_info.rectangle
                if rect.right <= 0 or rect.bottom <= 0:
                    continue
                if "填写作品标题" in name or "作品标题" in name or name == UPLOAD_EDIT_PLACEHOLDER:
                    target = control
                    break
            
            if not target:
                # 兜底：直接找靠右上方的大输入框
                edit_candidates = []
                for control in self.descendants():
                    if control.element_info.control_type not in ("Edit", "Document", "Text"):
                        continue
                    rect = control.element_info.rectangle
                    if rect.left > 1100 and rect.bottom > rect.top:
                        edit_candidates.append(control)
                if edit_candidates:
                    edit_candidates.sort(key=lambda c: (c.element_info.rectangle.top, c.element_info.rectangle.left))
                    target = edit_candidates[0]

            if target:
                break
            time.sleep(2)
            
        if not target:
            raise RuntimeError("未找到标题输入框。")
        
        try:
            win32gui.SetForegroundWindow(win32gui.FindWindow(None, APP_TITLE))
        except Exception:
            pass
            
        rect = target.element_info.rectangle
        mouse.click(button="left", coords=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
        time.sleep(0.5)
        
        # 输入标题（使用 Unicode 剪贴板，避免中文/emoji 文件名报编码错误）
        copy_text(full_text)
        keyboard.send_keys("^a{BACKSPACE}")
        time.sleep(0.2)
        keyboard.send_keys("^v")
        time.sleep(1)
        
        # 独立的话题填写逻辑：点击“#添加话题”区域
        topic_target = None
        self.refresh_window()
        for control in self.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            if name == "#添加话题" and rect.left > 1100:
                topic_target = control
                break
                
        if topic_target:
            rect = topic_target.element_info.rectangle
            mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
            time.sleep(1)
            
            # 逐个输入话题
            for ht in self.config.hashtags:
                copy_text(ht)
                keyboard.send_keys("^v")
                time.sleep(0.5)
                # 发送回车让抖音确认这是一个话题标签
                keyboard.send_keys("{ENTER}") 
                time.sleep(0.5)
        else:
            print("警告：未找到 '#添加话题' 入口，话题未添加。")

    def apply_first_ai_cover(self) -> None:
        self.clear_onboarding_popups()
        
        # Wait for "Ai智能推荐封面生成中..." to disappear, up to 15 seconds
        for _ in range(15):
            generating = False
            self.refresh_window()
            for control in self.descendants(control_type="Text"):
                if "生成中" in (control.element_info.name or ""):
                    generating = True
                    break
            if not generating:
                break
            time.sleep(1)

        images = []
        self.refresh_window()
        # Find the "查看封面展示页面" or "Ai智能推荐" text to locate the covers nearby
        for control in self.descendants():
            info = control.element_info
            rect = info.rectangle
            # We relax the horizontal bounds to support 4K monitors (e.g. rect.left > 1400)
            if info.control_type == "Image" and rect.left >= 1400 and rect.top >= 800 and rect.bottom <= 1500:
                # Filter out small icons
                if rect.right - rect.left > 50 and rect.bottom - rect.top > 50:
                    images.append(control)
        
        if not images:
            # Scroll a bit if not found
            mouse.scroll(coords=(1500, 800), wheel_dist=-3)
            time.sleep(2)
            self.refresh_window()
            for control in self.descendants():
                info = control.element_info
                rect = info.rectangle
                if info.control_type == "Image" and rect.left >= 1400 and rect.top >= 800 and rect.bottom <= 1500:
                    if rect.right - rect.left > 50 and rect.bottom - rect.top > 50:
                        images.append(control)
                    
        if not images:
            print("警告：未找到智能推荐封面，将跳过封面设置。")
            return
            
        # Click the first image
        rect = images[0].element_info.rectangle
        mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
        time.sleep(2)
        
        # Wait for confirmation button
        target = None
        for _ in range(3):
            self.refresh_window()
            for control in self.descendants(control_type="Button"):
                name = (control.element_info.name or "").strip()
                if name in ("确定", "确认", "应用", "完成"):
                    target = control
                    break
            if target:
                break
            time.sleep(2)
            
        if not target:
            print("警告：未找到确认应用封面的按钮，可能是自动保存或UI改变。")
            return
            
        rect = target.element_info.rectangle
        mouse.click(button="left", coords=((rect.left+rect.right)//2, (rect.top+rect.bottom)//2))
        time.sleep(2)

    def scroll_to_publish(self) -> None:
        mouse.scroll(coords=(1600, 1200), wheel_dist=-8)
        time.sleep(0.7)
        mouse.scroll(coords=(1600, 1200), wheel_dist=-8)
        time.sleep(1)

    def ensure_immediate_publish(self) -> None:
        self.refresh_window()
        for control in self.descendants():
            name = (control.element_info.name or "").strip()
            rect = control.element_info.rectangle
            if name == "立即发布" and rect.right > 0:
                control.click_input()
                time.sleep(0.5)
                return

    def final_publish(self) -> None:
        self.refresh_window()
        target = None
        for control in self.descendants(control_type="Button"):
            name = (control.element_info.name or "").strip()
            rect = control.element_info.rectangle
            if name == "发布" and rect.right > 0:
                target = control
        if not target:
            raise RuntimeError("未找到最终发布按钮。")
        target.click_input()
        self.publish_button_clicked = True
        time.sleep(self.config.publish_delay_sec)

    def publish_one(self, account_prefix: str, video_path: Path) -> None:
        self.click_account(account_prefix)
        self.goto_my_task()
        self.click_task_detail(self.config.task_title)
        self.click_upload_video_entry()
        self.upload_file(video_path)
        self.set_title_from_filename(video_path)
        self.apply_first_ai_cover()
        self.scroll_to_publish()
        self.ensure_immediate_publish()
        self.final_publish()
        self.record_published(account_prefix, video_path.name)
        print(f"发布流程已执行：{account_prefix} -> {safe_console_text(video_path.name)}")

    def move_to_published(self, video_path: Path, max_retries: int = 10, retry_wait_sec: int = 5) -> bool:
        import os
        destination = self.config.published_dir / video_path.name
        if not self.config.published_dir.exists():
            self.config.published_dir.mkdir(parents=True, exist_ok=True)
            
        for attempt in range(max_retries):
            try:
                if destination.exists():
                    destination.unlink()
                shutil.move(str(video_path), str(destination))
                print(f"已成功移动到：{safe_console_text(destination)}")
                return True
            except PermissionError:
                print(
                    f"文件被小豆芽占用，等待 {retry_wait_sec} 秒后重试 "
                    f"(尝试 {attempt+1}/{max_retries})：{safe_console_text(video_path.name)}"
                )
                time.sleep(retry_wait_sec)
            except Exception as e:
                print(f"移动文件失败：{e}")
                break
                
        # 如果还是移不走，尝试用 CMD 的 move 命令强制覆盖
        try:
            os.system(f'move /Y "{video_path}" "{destination}"')
            if not video_path.exists():
                print(f"通过 CMD 强行移动成功：{safe_console_text(destination)}")
                return True
        except Exception:
            pass
            
        print(f"最终未能移动文件：{safe_console_text(video_path.name)}，请后续手动移动。")
        return False

    def retry_pending_moves(self, videos: list[Path]) -> None:
        if not videos:
            return
        print(f"开始补偿移动 {len(videos)} 个发布成功视频...")
        for video in videos:
            if video.exists():
                self.move_to_published(video, max_retries=10, retry_wait_sec=5)


def main() -> int:
    try:
        config = load_config()
        XiaodouyaPoster(config).run()
        return 0
    except Exception as exc:
            import traceback
            with open("error_log.txt", "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            print(f"执行失败：{exc}，详情请看 error_log.txt", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
