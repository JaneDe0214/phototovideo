"""
斷點續傳快取與佇列管理單元測試
驗證：
1. 斷點續傳機制：已完成之片段自動命中快取跳過，接續剩餘項目；最終成功後自動清除暫存目錄。
2. 佇列管理機制：新增任務、排序、啟用/停用、JSON 儲存與重啟還原。
"""

import sys
import os
import shutil
import tempfile
import subprocess

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ffmpeg_engine import VideoRenderEngine, RenderConfig
from core.scanner import MediaItem
from core.queue_manager import QueueManager, BatchTask


def test_checkpoint_resume():
    print("=== [1] 測試斷點續傳 (Checkpoint Resume) 與空間釋放 ===")
    temp_dir = tempfile.mkdtemp(prefix="test_checkpoint_")

    try:
        # 建立兩張測試圖片
        img1 = os.path.join(temp_dir, "test1.jpg")
        img2 = os.path.join(temp_dir, "test2.jpg")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360", "-frames:v", "1", img1], capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360", "-frames:v", "1", img2], capture_output=True)

        config = RenderConfig(
            resolution="640x360",
            fps=30,
            vcodec="libx264",
            bitrate="2M",
            maxrate="3M",
            bufsize="5M",
            image_duration=1.0,
            fill_mode="black",
            concurrency=2,
            enable_auto_split=False
        )
        engine = VideoRenderEngine(config)

        media_items = [(MediaItem(img1), "Day1"), (MediaItem(img2), "Day1")]
        out_video = os.path.join(temp_dir, "Resume_Test.mp4")
        out_chap = os.path.join(temp_dir, "Resume_Test_Chapters.txt")

        # 模擬「上次中斷留下的快取」：手動為 item 1 建立合法的 seg_00000.mp4
        base_name = os.path.splitext(os.path.basename(out_video))[0]
        cache_dir = os.path.join(temp_dir, f".cache_{base_name}_p1")
        os.makedirs(cache_dir, exist_ok=True)
        cached_seg_0 = os.path.join(cache_dir, "seg_00000.mp4")

        # 預先生成 seg_00000.mp4
        ok = engine._render_image_segment(MediaItem(img1), cached_seg_0, 1.0, None, None)
        assert ok and os.path.exists(cached_seg_0) and os.path.getsize(cached_seg_0) > 1000, "預製快取必須成功"
        print(f"預製快取片段成功：{cached_seg_0} (大小: {os.path.getsize(cached_seg_0)} bytes)")

        # 執行完整合成，檢查是否自動偵測並跳過 seg_00000.mp4
        logs = []
        res = engine.render_album_to_video(
            media_items,
            out_video,
            out_chap,
            "斷點測試相簿",
            log_callback=lambda m: logs.append(m)
        )

        assert res is True, "渲染與合成必須成功"
        assert os.path.exists(out_video) and os.path.getsize(out_video) > 1000, "最終影片必須產出"
        
        # 驗證日誌中是否出現「斷點續傳生效」與「命中快取」
        has_resume_log = any("斷點續傳生效" in l for l in logs)
        print(f"是否成功觸發斷點續傳日誌: {has_resume_log}")
        assert has_resume_log, "必須觸發斷點續傳命中日誌！"

        # 驗證完成後暫存快取資料夾是否已被自動刪除（100% 釋出空間）
        cache_exists = os.path.exists(cache_dir)
        print(f"完成後快取資料夾是否已自動刪除: {not cache_exists}")
        assert not cache_exists, "任務完成後必須自動徹底清理快取目錄釋放空間！"

        print("[PASS] 斷點續傳與自動空間釋放驗證通過！\n")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_queue_manager():
    print("=== [2] 測試批次佇列管理器 (QueueManager) ===")
    temp_dir = tempfile.mkdtemp(prefix="test_queue_")
    storage_json = os.path.join(temp_dir, "test_queue.json")

    try:
        qm = QueueManager(storage_path=storage_json)

        # 建立兩個測試任務
        task1 = BatchTask(
            name="任務A_日本行",
            source_dir="D:/Photos/Japan",
            output_dir="D:/Output",
            profile_id="8k_hevc",
            profile_name="8K 60FPS",
            config_dict={"resolution": "7680x4320", "fps": 60}
        )
        task2 = BatchTask(
            name="任務B_露營日記",
            source_dir="D:/Photos/Camping",
            output_dir="D:/Output",
            profile_id="4k_hevc",
            profile_name="4K 60FPS",
            config_dict={"resolution": "3840x2160", "fps": 60}
        )

        qm.add_task(task1)
        qm.add_task(task2)
        assert len(qm.tasks) == 2, "佇列應有 2 個任務"

        # 測試順序調整
        qm.move_down(task1.task_id)
        assert qm.tasks[0].task_id == task2.task_id, "任務2 應被移至首位"

        qm.move_up(task1.task_id)
        assert qm.tasks[0].task_id == task1.task_id, "任務1 應移回首位"

        # 測試暫停/接續邏輯
        next_task = qm.get_next_runnable_task()
        assert next_task.task_id == task1.task_id, "下一個應執行的任務為任務1"

        qm.mark_task_status(task1.task_id, "paused", "使用者手動暫停", progress=45)
        assert qm.get_task(task1.task_id).progress_percent == 45, "進度應為 45%"

        # 測試重啟還原
        qm_reloaded = QueueManager(storage_path=storage_json)
        assert len(qm_reloaded.tasks) == 2, "重啟後應完整還原 2 個任務"
        assert qm_reloaded.tasks[0].status == "paused", "重啟後狀態應為 paused"

        # 測試清除已完成
        qm.mark_task_status(task2.task_id, "completed", "已完成", progress=100)
        removed = qm.clear_completed()
        assert removed == 1 and len(qm.tasks) == 1, "應成功清除 1 個已完成任務"

        print("[PASS] 批次佇列管理器功能驗證通過！\n")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_checkpoint_resume()
    test_queue_manager()
    print("[ALL PASS] 斷點續傳與批次佇列核心測試全數通過！")
