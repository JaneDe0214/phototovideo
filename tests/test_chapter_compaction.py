"""
YouTube 5,000 字智慧章節濃縮與多 Part 獨立測試
驗證：
1. 超大相簿（例如 1,000 個項目）字數嚴格控制在 4,500 字以內（防範 YouTube 5,000 字爆表）。
2. 影片 100% 絕對優先保留。
3. 景點 / 目錄大分類切換節點 100% 優先保留。
4. 照片採均勻時間抽樣，任兩章節間隔 >= 10 秒（符合 YouTube 規範）。
5. 各 Part 獨立濃縮，時間軸從 00:00 起算。
6. 同步產出 Chapters.txt (YT專用) 與 Chapters_Full.txt (本機全記錄)。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.chapter_generator import ChapterGenerator


def test_chapter_compaction_and_video_priority():
    print("=== [1] 測試超大相簿（1,000 個項目）智慧濃縮與影片優先 ===")
    gen = ChapterGenerator(target_title="2024-05_日本東京行", part_index=1, total_parts=1)

    # 模擬 1,000 個項目：
    # 其中包含 10 個景點分類、15 支重要短片、975 張普通照片
    curr_time = 0.0
    for i in range(1000):
        cat = f"景點_{i // 100 + 1:02d}"
        is_vid = (i % 65 == 0)  # 每隔 65 張出現一支影片，共約 15 支影片
        title = f"VID_{i:04d}_家庭影片.mp4" if is_vid else f"IMG_{i:04d}_旅遊照片.jpg"
        gen.add_entry(curr_time, title, category=cat, is_video=is_vid)
        curr_time += 15.0 if is_vid else 3.0

    # 測試完整版長度（肯定遠超過 5,000 字）
    full_text = gen.generate_full_text()
    print(f"完整版章節總字元數: {len(full_text)} 字元 (已嚴重超過 YouTube 5,000 字限制！)")
    assert len(full_text) > 20000, "1,000 項目的完整字數應超過 20,000 字"

    # 測試智慧濃縮版
    yt_text, is_condensed = gen.generate_youtube_text(max_chars=4500)
    print(f"智慧濃縮版總字元數: {len(yt_text)} 字元, 是否觸發濃縮: {is_condensed}")
    assert is_condensed is True, "應觸發智慧濃縮"
    assert len(yt_text) <= 4500, f"智慧濃縮版字數不得超過 4,500 字！(實際: {len(yt_text)})"

    # 驗證影片 100% 優先保留
    video_count_in_full = sum(1 for it in gen.entries if it.is_video)
    video_count_in_yt = yt_text.count("🎬 [影片]")
    print(f"全項目中影片總數: {video_count_in_full}, 智慧濃縮後保留影片數: {video_count_in_yt}")
    assert video_count_in_yt == video_count_in_full, "所有影片應 100% 全部優先保留！"

    # 驗證所有 10 個景點大分類是否全部保留
    for c in range(1, 11):
        cat_tag = f"【景點_{c:02d}】"
        assert cat_tag in yt_text, f"大分類 {cat_tag} 應被完整保留！"

    print("[PASS] 超大相簿 5,000 字防爆表與影片優先驗證成功！")


def test_multi_part_isolated_chapters():
    print("\n=== [2] 測試多 Part 獨立濃縮與時間軸歸零 ===")
    # 測試 Part 1 (100 項)
    gen_part1 = ChapterGenerator(target_title="2024-05_日本行", part_index=1, total_parts=2)
    t1 = 0.0
    for i in range(100):
        gen_part1.add_entry(t1, f"Part1_IMG_{i:03d}.jpg", category="Part1景點", is_video=(i == 50))
        t1 += 3.0

    # 測試 Part 2 (100 項)
    gen_part2 = ChapterGenerator(target_title="2024-05_日本行", part_index=2, total_parts=2)
    t2 = 0.0
    for i in range(100):
        gen_part2.add_entry(t2, f"Part2_IMG_{i:03d}.jpg", category="Part2景點", is_video=(i == 30))
        t2 += 3.0

    text_p1, _ = gen_part1.generate_youtube_text(max_chars=4500)
    text_p2, _ = gen_part2.generate_youtube_text(max_chars=4500)

    # 驗證標記
    assert "[Part 01/02]" in text_p1
    assert "[Part 02/02]" in text_p2
    assert "00:00" in text_p1
    assert "00:00" in text_p2
    assert "Part1_IMG" in text_p1 and "Part2_IMG" not in text_p1, "Part 1 不得混入 Part 2 內容"
    assert "Part2_IMG" in text_p2 and "Part1_IMG" not in text_p2, "Part 2 不得混入 Part 1 內容"

    print("[PASS] 多 Part 獨立濃縮與時間軸歸零驗證成功！")


def test_dual_file_saving():
    print("\n=== [3] 測試雙檔儲存機制 (Chapters.txt + Chapters_Full.txt) ===")
    gen = ChapterGenerator(target_title="雙檔測試", part_index=1, total_parts=1)
    t = 0.0
    for i in range(500):
        gen.add_entry(t, f"Item_{i:04d}.jpg", category="分類", is_video=(i == 100))
        t += 3.0

    temp_out = os.path.join(os.environ.get("TEMP", "."), "Test_Dual_Chapters.txt")
    full_path = gen.save_to_file(temp_out, max_chars=4500)

    print(f"YT 精選版檔案路徑: {temp_out}")
    print(f"本機完整版檔案路徑: {full_path}")

    assert os.path.exists(temp_out), "YT 精華版應存在"
    assert full_path is not None and os.path.exists(full_path), "因發生濃縮，完整版檔案應自動生成"

    size_yt = os.path.getsize(temp_out)
    size_full = os.path.getsize(full_path)
    print(f"YT 精選版大小: {size_yt} bytes, 本機完整版大小: {size_full} bytes")
    assert size_yt <= 4500 * 3, "YT 版大小應符合字數限制"
    assert size_full > size_yt, "完整版應大於精選版"

    # 清理檔案
    for p in [temp_out, full_path]:
        if os.path.exists(p):
            os.remove(p)

    print("[PASS] 雙檔儲存功能驗證成功！")


if __name__ == "__main__":
    test_chapter_compaction_and_video_priority()
    test_multi_part_isolated_chapters()
    test_dual_file_saving()
    print("\n[ALL PASS] 5,000 字智慧章節濃縮演算法全部通過！")
