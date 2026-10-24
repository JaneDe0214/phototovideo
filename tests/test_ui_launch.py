"""
UI 視窗初始化與元件完整性測試
"""

import os
import sys

# 將專案根目錄加入模組搜尋路徑
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.styles import DARK_THEME


def test_ui():
    print("=== [UI 測試] 正在初始化 QApplication 與 MainWindow ===")
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)

    window = MainWindow()
    assert window is not None, "MainWindow 實例不可為 None"
    print("MainWindow 實例建立成功。")

    # 驗證所有關鍵 UI 元件是否存在
    assert hasattr(window, "tab_widget"), "缺少 tab_widget"
    assert window.tab_widget.count() == 2, "TabWidget 應具有 2 個頁籤"
    assert hasattr(window, "btn_add_to_queue"), "缺少 btn_add_to_queue"
    assert hasattr(window, "btn_select_root"), "缺少 btn_select_root"
    assert hasattr(window, "tree_widget"), "缺少 tree_widget"
    assert hasattr(window, "combo_profile"), "缺少 combo_profile"
    assert hasattr(window, "chk_auto_split"), "缺少 chk_auto_split"
    assert hasattr(window, "chk_custom_out"), "缺少 chk_custom_out"
    assert hasattr(window, "txt_custom_out_dir"), "缺少 txt_custom_out_dir"
    assert hasattr(window, "btn_browse_out"), "缺少 btn_browse_out"
    assert hasattr(window, "btn_start"), "缺少 btn_start"
    assert hasattr(window, "progress_bar"), "缺少 progress_bar"
    assert hasattr(window, "queue_table"), "缺少 queue_table"
    assert hasattr(window, "btn_queue_start"), "缺少 btn_queue_start"
    assert hasattr(window, "btn_queue_pause"), "缺少 btn_queue_pause"
    assert hasattr(window, "chk_auto_shutdown"), "缺少 chk_auto_shutdown"
    print("所有核心 UI 元件（包含批次佇列與分頁）屬性檢查通過。")

    # 測試自訂輸出路徑勾選切換
    window.chk_custom_out.setChecked(True)
    assert window.txt_custom_out_dir.isEnabled() == True, "自訂路徑輸入框應已啟用"
    assert window.btn_browse_out.isEnabled() == True, "瀏覽按鈕應已啟用"

    window.txt_custom_out_dir.setText(r"D:\Test_Output")
    eff_dir = window._get_effective_output_dir()
    assert "Test_Output" in eff_dir, f"有效目錄計算錯誤: {eff_dir}"
    print(f"有效輸出目錄切換測試成功: {eff_dir}")

    # 測試切換回預設起點路徑
    window.chk_custom_out.setChecked(False)
    assert window.txt_custom_out_dir.isEnabled() == False, "自訂路徑輸入框應已停用"
    print("切換回預設輸出模式測試成功。")

    print("\n[PASS] UI 元件與視窗載入測試完全通過！")


if __name__ == "__main__":
    test_ui()
