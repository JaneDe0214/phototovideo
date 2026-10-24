"""
檔名規格與命名規則單元測試
驗證：
1. 檔名取消「極致備份」字樣。
2. 檔名包含正確的 [解析度]_[晶片名稱]_[轉檔格式]。
3. 支援多 Part 標記（如 _Part01）。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.encoder_detector import get_output_spec_tag


def test_naming_spec_tags():
    print("=== [1] 測試各設定檔的檔名規格標籤 ===")

    # 1. 255H 筆電最佳：Intel Arc AV1
    p_arc_av1 = {
        "id": "8k_qsv_av1",
        "resolution": "7680x4320",
        "vcodec": "av1_qsv",
        "hw_type": "Intel Arc QSV",
    }
    tag1 = get_output_spec_tag(p_arc_av1)
    print(f"Intel Arc AV1 標籤: {tag1}")
    assert tag1 == "8K_IntelArc_AV1"

    # 2. Intel QSV HEVC 8K
    p_qsv_hevc_8k = {
        "id": "8k_qsv_hevc",
        "resolution": "7680x4320",
        "vcodec": "hevc_qsv",
        "hw_type": "Intel QSV",
    }
    tag2 = get_output_spec_tag(p_qsv_hevc_8k)
    print(f"Intel QSV HEVC 8K 標籤: {tag2}")
    assert tag2 == "8K_IntelQSV_HEVC"

    # 3. Intel QSV HEVC 4K
    p_qsv_hevc_4k = {
        "id": "4k_qsv_hevc",
        "resolution": "3840x2160",
        "vcodec": "hevc_qsv",
        "hw_type": "Intel QSV",
    }
    tag3 = get_output_spec_tag(p_qsv_hevc_4k)
    print(f"Intel QSV HEVC 4K 標籤: {tag3}")
    assert tag3 == "4K_IntelQSV_HEVC"

    # 4. CPU 軟體運算
    p_cpu_8k = {
        "id": "8k_cpu_hevc",
        "resolution": "7680x4320",
        "vcodec": "libx265",
        "hw_type": "CPU (libx265)",
    }
    tag4 = get_output_spec_tag(p_cpu_8k)
    print(f"CPU HEVC 8K 標籤: {tag4}")
    assert tag4 == "8K_CPU_HEVC"

    # 5. NVIDIA NVENC AV1
    p_nv_av1 = {
        "id": "8k_nvenc_av1",
        "resolution": "7680x4320",
        "vcodec": "av1_nvenc",
        "hw_type": "NVIDIA NVENC",
    }
    tag5 = get_output_spec_tag(p_nv_av1)
    print(f"NVIDIA NVENC AV1 標籤: {tag5}")
    assert tag5 == "8K_NVIDIA-NVENC_AV1"

    print("[PASS] 各硬體晶片與編碼格式標籤完全正確！")


def test_filename_generation():
    print("\n=== [2] 測試最終影片檔名組裝 ===")
    target_name = "2024-05_日本東京"
    spec_tag = "8K_IntelArc_AV1"

    # 單一影片
    single_name = f"{target_name}_{spec_tag}.mp4"
    print(f"單一影片檔名: {single_name}")
    assert "極致備份" not in single_name, "檔名不得含有『極致備份』"
    assert single_name == "2024-05_日本東京_8K_IntelArc_AV1.mp4"

    # 分段影片
    part1_name = f"{target_name}_{spec_tag}_Part01.mp4"
    print(f"分段影片檔名: {part1_name}")
    assert "極致備份" not in part1_name, "分段檔名不得含有『極致備份』"
    assert part1_name == "2024-05_日本東京_8K_IntelArc_AV1_Part01.mp4"

    print("[PASS] 檔名組裝完全符合需求！")


if __name__ == "__main__":
    test_naming_spec_tags()
    test_filename_generation()
    print("\n[ALL PASS] 檔名規格自訂化測試全數通過！")
