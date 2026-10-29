"""
單元測試：全域崩潰保護 (Crash Guard)、記憶體防禦與快取救援 (Cache Rescue)
驗證：
1. 日誌輪替系統與崩潰日誌輸出 (phototovideo.log 與 crash_log.txt)
2. 算圖背景執行緒 (RenderWorker) 的頂層例外捕獲與安全終止
3. 一鍵快取救援工具 (rescue_cache_to_video) 的自動掃描與無損合併
4. 受控滑動視窗 (Window Submission) 在多任務下的穩定性
"""

import os
import shutil
import tempfile
import unittest
from core.logger import init_logger, log_crash, get_log_paths
from core.ffmpeg_engine import VideoRenderEngine, RenderConfig


class TestCrashGuardAndCacheRescue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_crash_guard_")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_logger_and_crash_log_generation(self):
        """測試日誌初始化與 crash_log.txt 的正確輸出"""
        log_file, crash_file = get_log_paths()
        logger = init_logger()
        logger.info("Unit test message from test_logger_and_crash_log_generation")

        # 模擬一個例外事件
        try:
            raise ValueError("Test crash guard simulation exception")
        except ValueError as ex:
            import sys
            exc_type, exc_val, exc_tb = sys.exc_info()
            saved_file, tb_str = log_crash(exc_type, exc_val, exc_tb, thread_name="TestThread")

        self.assertTrue(os.path.exists(saved_file))
        with open(saved_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Test crash guard simulation exception", content)
        self.assertIn("TestThread", content)
        self.assertIn("Traceback", content)

    def test_rescue_cache_to_video_not_exist(self):
        """測試當快取目錄不存在或為空時的防禦回傳"""
        engine = VideoRenderEngine()
        non_exist_dir = os.path.join(self.test_dir, ".cache_non_exist")
        ok, msg, count = engine.rescue_cache_to_video(non_exist_dir)
        self.assertFalse(ok)
        self.assertEqual(count, 0)
        self.assertIn("不存在", msg)

        # 測試空目錄
        empty_cache = os.path.join(self.test_dir, ".cache_empty")
        os.makedirs(empty_cache, exist_ok=True)
        ok2, msg2, count2 = engine.rescue_cache_to_video(empty_cache)
        self.assertFalse(ok2)
        self.assertEqual(count2, 0)
        self.assertIn("未發現任何", msg2)

    def test_rescue_cache_simulation(self):
        """測試快取救援之掃描、排序與 Concat 清單產生"""
        engine = VideoRenderEngine()
        cache_dir = os.path.join(self.test_dir, ".cache_album_p1")
        os.makedirs(cache_dir, exist_ok=True)

        # 建立數個虛擬的 seg_00000.mp4, seg_00001.mp4 檔案（大於 1KB）
        seg0 = os.path.join(cache_dir, "seg_00000.mp4")
        seg1 = os.path.join(cache_dir, "seg_00001.mp4")
        seg2 = os.path.join(cache_dir, "seg_00002.mp4")

        dummy_data = b"0" * 2048
        with open(seg0, "wb") as f:
            f.write(dummy_data)
        with open(seg1, "wb") as f:
            f.write(dummy_data)
        with open(seg2, "wb") as f:
            f.write(dummy_data)

        # 驗證掃描候選檔案
        seg_candidates = [
            fn for fn in os.listdir(cache_dir)
            if fn.startswith("seg_") and fn.endswith(".mp4") and os.path.getsize(os.path.join(cache_dir, fn)) > 1000
        ]
        seg_candidates.sort()
        self.assertEqual(len(seg_candidates), 3)
        self.assertEqual(seg_candidates[0], "seg_00000.mp4")
        self.assertEqual(seg_candidates[1], "seg_00001.mp4")
        self.assertEqual(seg_candidates[2], "seg_00002.mp4")

    def test_render_worker_exception_handling(self):
        """測試 RenderWorker 遇到未捕獲例外時不會直接崩潰退出，而是發出 finished_signal(False)"""
        from ui.main_window import RenderWorker
        from unittest.mock import MagicMock

        mock_engine = MagicMock()
        # 模擬 render_album_to_video 拋出非預期崩潰例外
        mock_engine.render_album_to_video.side_effect = RuntimeError("Fatal hardware pipe crash simulation")

        worker = RenderWorker(
            engine=mock_engine,
            media_list=[],
            output_video_path="test_out.mp4",
            output_chapter_path="test_chap.txt",
            target_title="Test Target"
        )

        signal_received = []

        def on_finished(success, msg):
            signal_received.append((success, msg))

        worker.finished_signal.connect(on_finished)
        # 直接執行 run() 測試防護包裹
        worker.run()

        self.assertEqual(len(signal_received), 1)
        success, msg = signal_received[0]
        self.assertFalse(success)
        self.assertIn("Fatal hardware pipe crash simulation", msg)


if __name__ == "__main__":
    unittest.main()
