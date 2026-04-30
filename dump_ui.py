import win32gui
import win32con
from pywinauto import Desktop
import time

def dump_ui():
    print("Finding window...")
    hwnd = win32gui.FindWindow(None, "新榜小豆芽")
    if not hwnd:
        print("Not found")
        return
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(1)
    
    desktop = Desktop(backend="uia")
    window = desktop.window(title="新榜小豆芽")
    
    with open("ui_dump.txt", "w", encoding="utf-8") as f:
        for control in window.descendants():
            info = control.element_info
            name = (info.name or "").strip()
            rect = info.rectangle
            f.write(f"Type: {info.control_type}, Name: '{name}', Rect: ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})\n")
    print("Done")

if __name__ == "__main__":
    dump_ui()
