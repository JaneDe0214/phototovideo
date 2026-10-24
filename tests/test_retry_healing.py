"""
自動自癒重試修復單元測試
驗證：
當硬體編碼器遇到 [av1_qsv] Error allocating output packet 或任何致命異常時，
系統能自動啟動多階段自癒重試（自適應緩衝、切換成熟 HEVC 硬體、CPU 軟體無損保底），
絕不跳過任何一張相片或影片！
"""

import sys
import os
import subprocess

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ffmpeg_engine import VideoRenderEngine, RenderConfig
from core.scanner import MediaItem


def test_self_healing_retry():
    print("=== 測試相片編碼失敗自動自癒修復機制 ===")

    # 刻意給一個當前環境絕對不支援的編碼器（如不存在的 invalid_qsv），模擬 av1_qsv 顯存崩潰
    config = RenderConfig(
        resolution="640x360",
        fps=30,
        vcodec="invalid_qsv_codec",  # 刻意觸發第一階段失敗
        fill_mode="black",
        image_duration=1.0,
    )
    engine = VideoRenderEngine(config)

    temp_dir = os.path.join(os.environ.get("TEMP", "."), "test_healing_dir")
    os.makedirs(temp_dir, exist_ok=True)
    test_img = os.path.join(temp_dir, "healing_test.jpg")
    subprocess.run(
        [
            engine.ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=640x360",
            "-frames:v",
            "1",
            test_img,
        ],
        capture_output=True,
    )

    out_file = os.path.join(temp_dir, "healing_out.mp4")
    logs = []

    def _log(msg):
        logs.append(msg)
        print("  LOG ->", msg)

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    item = MediaItem(test_img)
    print(">>> 呼叫 _render_image_segment...")
    ok = engine._render_image_segment(
        item, out_file, 1.0, startupinfo, log_callback=_log
    )

    print(f"渲染結果: {ok}, 檔案是否存在: {os.path.exists(out_file)}")
    assert ok is True, "即便原始編碼器崩潰，自癒體系也必須透過保底方案成功渲染！"
    assert os.path.exists(out_file) and os.path.getsize(out_file) > 1000, "修復後的檔案必須有效存在！"

    # 檢查是否記錄了自動修復日誌
    has_repair_log = any("自動修復" in l for l in logs)
    has_success_log = any("自動修復成功" in l for l in logs)
    print(f"是否觸發自動修復日誌: {has_repair_log}, 是否觸發修復成功日誌: {has_success_log}")
    assert has_repair_log and has_success_log, "應完整記錄自動修復與成功日誌"

    # 清理
    for f in [test_img, out_file]:
        if os.path.exists(f):
            os.remove(f)

    print("[PASS] 自動自癒修復機制驗證成功！絕不跳過任何相片！")


if __name__ == "__main__":
    test_self_healing_retry()
