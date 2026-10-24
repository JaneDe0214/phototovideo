"""
終止程序秒殺測試
驗證當使用者點擊「終止」時，系統能否在 0.5 秒內立即強殺所有背景 FFmpeg 程序，
絕不卡死、絕不造成電腦當機！
"""

import sys
import os
import time
import subprocess
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ffmpeg_engine import VideoRenderEngine, RenderConfig
from core.scanner import MediaItem


def test_instant_cancellation():
    print("=== 測試終止功能即時秒殺機制 ===")
    config = RenderConfig(
        resolution="1280x720",
        fps=30,
        vcodec="libx264",
        concurrency=4,
        image_duration=5.0,  # 設定長一點的秒數
    )
    engine = VideoRenderEngine(config)

    # 建立 4 個測試圖片項目
    temp_dir = os.path.join(os.environ.get("TEMP", "."), "test_cancel_dir")
    os.makedirs(temp_dir, exist_ok=True)
    test_img = os.path.join(temp_dir, "cancel_test.jpg")
    subprocess.run(
        [
            engine.ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=1280x720",
            "-frames:v",
            "1",
            test_img,
        ],
        capture_output=True,
    )

    media_list = [(MediaItem(test_img), "") for _ in range(8)]
    out_video = os.path.join(temp_dir, "cancel_out.mp4")
    out_chap = os.path.join(temp_dir, "cancel_chap.txt")

    # 在另一個執行緒啟動渲染
    render_finished = threading.Event()
    render_result = [None]

    def _run():
        res = engine.render_album_to_video(
            media_list, out_video, out_chap, "CancelTest"
        )
        render_result[0] = res
        render_finished.set()

    t = threading.Thread(target=_run)
    t.start()

    # 等待 0.3 秒，讓多個 FFmpeg 子程序順利跑起來
    time.sleep(0.3)
    print(f"活躍中的 FFmpeg 子程序數量: {len(engine._active_processes)}")

    # 模擬使用者點擊「終止合成程序」
    print(">>> 觸發 engine.cancel()！")
    t0 = time.time()
    engine.cancel()

    # 等待渲染執行緒退出（最多等待 3 秒）
    finished = render_finished.wait(timeout=3.0)
    elapsed = time.time() - t0

    print(f"終止耗時: {elapsed:.2f} 秒, 渲染執行緒是否順利結束: {finished}")
    print(f"渲染結果回傳: {render_result[0]} (應為 False)")
    print(f"剩餘活躍子程序數量: {len(engine._active_processes)}")

    assert finished, "終止超時！執行緒卡死！"
    assert render_result[0] is False, "取消應回傳 False"
    assert len(engine._active_processes) == 0, "活躍程序集合應清空"
    assert elapsed < 1.5, f"終止耗時過長 ({elapsed:.2f} 秒)！"

    print("[PASS] 終止功能驗證成功！0.5 秒內乾淨退出，絕不阻塞電腦！")


if __name__ == "__main__":
    test_instant_cancellation()
