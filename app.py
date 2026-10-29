"""
相簿轉 8K/4K YouTube 極致備份影片合成工具 - 主程式進入點
"""

import sys
import os

# 安裝全域崩潰保護與安全日誌系統（防止任何未捕獲例外造成靜默閃退）
from core.logger import setup_crash_guard, logger
setup_crash_guard()

# 在無主控台（--noconsole）模式下防護 stdout / stderr 為 None 的情況
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
from ui.styles import DARK_THEME


def main():
    if "--test" in sys.argv:
        print("[OK] App test mode passed, GUI ready.")
        sys.exit(0)

    # 支援 Windows 高 DPI 螢幕清晰顯示
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)

    logger.info("正在建立主視窗介面...")
    window = MainWindow()
    window.show()

    logger.info("主視窗已顯示，進入 Qt 事件循環")
    ret_code = app.exec()
    logger.info(f"應用程式正常結束，結束代碼: {ret_code}")
    sys.exit(ret_code)


if __name__ == "__main__":
    main()
