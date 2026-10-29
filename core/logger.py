"""
全域安全日誌與崩潰保護系統 (Crash Guard & Rotating File Logger)
提供：
1. 自動記錄執行歷程至 phototovideo.log (自動輪替限制容量，保護硬碟空間)
2. 全域未捕獲例外攔截 (sys.excepthook, threading.excepthook)，寫入 crash_log.txt
3. GUI 崩潰彈窗警示，徹底告別無預警靜默關閉
"""

import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import sys
import threading
import traceback
from datetime import datetime

# 全域 Logger 實例
logger = logging.getLogger("PhotoToVideo")
logger.setLevel(logging.INFO)

_is_guard_installed = False
_log_file_path = ""
_crash_log_path = ""


def get_log_paths() -> tuple:
    """取得日誌與崩潰報告之路徑"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = os.path.join(base_dir, "phototovideo.log")
    crash_file = os.path.join(base_dir, "crash_log.txt")
    return log_file, crash_file


def init_logger():
    """初始化檔案與控制台日誌輪替系統"""
    global _log_file_path, _crash_log_path
    if logger.handlers:
        return logger

    _log_file_path, _crash_log_path = get_log_paths()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. 檔案輪替 Handler (上限 10MB，保留 3 份歷史紀錄，防硬碟被塞滿)
    try:
        file_handler = RotatingFileHandler(
            _log_file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[WARN] 無法建立檔案日誌: {e}")

    # 2. 控制台 Handler (若非 pythonw 且 stdout 可用)
    if sys.stdout is not None and not getattr(sys.stdout, "closed", False):
        try:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(logging.INFO)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)
        except Exception:
            pass

    logger.info("PhotoToVideo 記錄器已成功初始化")
    return logger


def log_crash(exc_type, exc_value, exc_traceback, thread_name="MainThread"):
    """記錄嚴重崩潰例外至 crash_log.txt"""
    _, crash_file = get_log_paths()
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_text = "".join(tb_lines)

    report = [
        "=" * 70,
        f"🚨【PhotoToVideo 應用程式異常終止報告】",
        f"發生時間: {time_str}",
        f"所在執行緒: {thread_name}",
        f"作業系統: {platform.platform()} ({platform.architecture()[0]})",
        f"Python 版本: {platform.python_version()} ({sys.executable})",
        "=" * 70,
        "【詳細錯誤堆疊 (Traceback)】:",
        tb_text,
        "=" * 70 + "\n",
    ]
    report_text = "\n".join(report)

    try:
        with open(crash_file, "a", encoding="utf-8") as f:
            f.write(report_text)
    except Exception as e:
        print(f"[FATAL] 無法寫入崩潰日誌: {e}")

    if logger:
        logger.critical(f"應用程式遭遇未捕獲例外崩潰！已存入 {crash_file}\n{tb_text}")

    return crash_file, tb_text


def setup_crash_guard(app_instance=None):
    """安裝全域例外與崩潰防護器"""
    global _is_guard_installed
    if _is_guard_installed:
        return
    _is_guard_installed = True

    init_logger()

    def handle_sys_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        crash_file, tb_text = log_crash(exc_type, exc_value, exc_traceback, thread_name="Main")

        # 若在 PyQt GUI 運行中，嘗試彈出緊急錯誤對話方塊
        try:
            from PyQt6.QtWidgets import QMessageBox, QApplication
            if QApplication.instance():
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Critical)
                msg_box.setWindowTitle("PhotoToVideo - 程式執行異常")
                msg_box.setText(
                    f"⚠️ 程式遇到非預期錯誤，已安全攔截並記錄現場！\n\n"
                    f"錯誤類型：{exc_type.__name__}\n"
                    f"詳細報告已儲存至：\n{crash_file}\n\n"
                    f"您可以將該報告回報給開發團隊以迅速修復。"
                )
                msg_box.setDetailedText(tb_text)
                msg_box.exec()
        except Exception:
            pass

    def handle_threading_exception(args):
        log_crash(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            thread_name=args.thread.name if args.thread else "BackgroundThread",
        )

    sys.excepthook = handle_sys_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_threading_exception

    logger.info("全域崩潰保護器 (Crash Guard) 已就緒")
