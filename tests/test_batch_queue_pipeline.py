"""
批次佇列與自動排程端到端流水線整合測試
驗證：
1. 佇列依序自動執行多個不同相簿資料夾之任務 (任務 1 -> 任務 2)。
2. 每個任務獨立產出對應之 8K/4K 影片與章節索引。
3. 任務完成後各自之暫存快取目錄自動 100% 清除釋放空間。
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
from core.scanner import AlbumScanner
from core.queue_manager import QueueManager, BatchTask


def test_batch_queue_pipeline():
    print("=== 測試批次佇列端到端自動流水線 ===")
    temp_root = tempfile.mkdtemp(prefix="test_batch_pipeline_")
    storage_json = os.path.join(temp_root, "test_queue.json")

    try:
        # 1. 建立兩個獨立相簿資料夾
        album_a = os.path.join(temp_root, "2024-01_北海道")
        album_b = os.path.join(temp_root, "2024-07_沖繩海灘")
        os.makedirs(album_a, exist_ok=True)
        os.makedirs(album_b, exist_ok=True)

        out_dir = os.path.join(temp_root, "Batch_Output")
        os.makedirs(out_dir, exist_ok=True)

        # 在相簿 A 建立圖片
        img_a1 = os.path.join(album_a, "hokkaido_1.jpg")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360", "-frames:v", "1", img_a1], capture_output=True)

        # 在相簿 B 建立圖片
        img_b1 = os.path.join(album_b, "okinawa_1.jpg")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=640x360", "-frames:v", "1", img_b1], capture_output=True)

        # 2. 建立 QueueManager 並加入這兩個任務
        qm = QueueManager(storage_path=storage_json)

        task1 = BatchTask(
            name="2024-01_北海道",
            source_dir=album_a,
            output_dir=out_dir,
            profile_id="test_720p",
            profile_name="測試規格 720P",
            config_dict={
                "resolution": "640x360",
                "fps": 30,
                "vcodec": "libx264",
                "bitrate": "2M",
                "maxrate": "3M",
                "bufsize": "5M",
                "image_duration": 1.0,
                "fill_mode": "black",
                "enable_auto_split": False,
                "concurrency": 2,
            },
            total_items=1,
            output_video_path=os.path.join(out_dir, "2024-01_北海道_Test.mp4"),
            output_chapter_path=os.path.join(out_dir, "2024-01_北海道_Chapters.txt"),
        )

        task2 = BatchTask(
            name="2024-07_沖繩海灘",
            source_dir=album_b,
            output_dir=out_dir,
            profile_id="test_720p",
            profile_name="測試規格 720P",
            config_dict={
                "resolution": "640x360",
                "fps": 30,
                "vcodec": "libx264",
                "bitrate": "2M",
                "maxrate": "3M",
                "bufsize": "5M",
                "image_duration": 1.0,
                "fill_mode": "black",
                "enable_auto_split": False,
                "concurrency": 2,
            },
            total_items=1,
            output_video_path=os.path.join(out_dir, "2024-07_沖繩海灘_Test.mp4"),
            output_chapter_path=os.path.join(out_dir, "2024-07_沖繩海灘_Chapters.txt"),
        )

        qm.add_task(task1)
        qm.add_task(task2)
        print(f"佇列已加入 2 個任務：{[t.name for t in qm.tasks]}")

        # 3. 模擬批次自動執行循環
        processed_tasks = 0
        while True:
            task = qm.get_next_runnable_task()
            if not task:
                break

            processed_tasks += 1
            print(f"\n>>> 正在執行批次佇列第 {processed_tasks} 個任務：『{task.name}』...")
            qm.mark_task_status(task.task_id, "running", "處理中...")

            # 掃描來源
            root = AlbumScanner.scan_directory_tree(task.source_dir)
            sorted_media = AlbumScanner.get_sorted_media_from_node(root)
            cfg = task.config_dict

            engine = VideoRenderEngine(RenderConfig(
                resolution=cfg["resolution"],
                fps=cfg["fps"],
                vcodec=cfg["vcodec"],
                bitrate=cfg["bitrate"],
                maxrate=cfg["maxrate"],
                bufsize=cfg["bufsize"],
                image_duration=cfg["image_duration"],
                fill_mode=cfg["fill_mode"],
                enable_auto_split=cfg["enable_auto_split"],
                concurrency=cfg["concurrency"],
            ))

            ok = engine.render_album_to_video(
                sorted_media,
                task.output_video_path,
                task.output_chapter_path,
                task.name,
                log_callback=lambda m: print(f"  [{task.name}] {m}")
            )

            assert ok, f"任務『{task.name}』合成必須成功！"
            assert os.path.exists(task.output_video_path), f"影片必須產出：{task.output_video_path}"
            assert os.path.exists(task.output_chapter_path), f"章節必須產出：{task.output_chapter_path}"

            qm.mark_task_status(task.task_id, "completed", "已完成", progress=100)

        assert processed_tasks == 2, "應依序完成全部 2 個佇列任務"
        assert all(t.status == "completed" for t in qm.tasks), "所有任務狀態應為 completed"

        # 4. 驗證暫存快取是否全部被自動清理
        cache_dirs = [d for d in os.listdir(out_dir) if d.startswith(".cache_") or d.startswith("_temp_render_")]
        print(f"輸出目錄中殘留的快取資料夾數量: {len(cache_dirs)}")
        assert len(cache_dirs) == 0, "所有任務完成後暫存快取目錄必須被自動 100% 清空釋放空間！"

        print("\n[PASS] 批次佇列端到端流水線與自動空間釋放驗證成功！")

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    test_batch_queue_pipeline()
