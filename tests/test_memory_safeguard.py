"""
記憶體安全防護與 SSD SWAP 防護單元測試
驗證在 16GB、32GB、64GB 以及 4K/8K 解析度下的安全平行緒數計算
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.encoder_detector import calculate_safe_concurrency, get_system_memory_info


def test_memory_detection():
    print("=== [1] 測試系統實體記憶體偵測 ===")
    info = get_system_memory_info()
    print(f"偵測到實體總記憶體: {info['total_gb']} GB, 可用記憶體: {info['avail_gb']} GB")
    assert info["total_gb"] > 0, "實體記憶體容量應大於 0"
    print("[PASS] 實體記憶體偵測成功！")


def test_concurrency_calculation():
    print("\n=== [2] 測試不同硬體規格下的安全執行緒數計算 ===")

    # 模擬 1：使用者 32GB 筆電 (Core Ultra 155H, 16 緒)
    # 8K 模式：必須防止 32GB 記憶體吃滿進 SWAP
    concur_32g_8k = calculate_safe_concurrency(total_ram_gb=32.0, is_8k=True, max_cores=16)
    print(f"32GB 筆電在 8K 模式下的安全平行緒數: {concur_32g_8k} 緒")
    assert 4 <= concur_32g_8k <= 10, f"32GB 筆電跑 8K 應限制在 4~10 緒，避免 SWAP (實際: {concur_32g_8k})"
    est_ram = concur_32g_8k * 1.8 + 6.0
    print(f"  預估尖峰 RAM 佔用: {est_ram:.1f} GB (小於 32GB，100% 零 SWAP！)")

    # 4K 模式：4K 記憶體佔用小，允許較高緒數狂飆
    concur_32g_4k = calculate_safe_concurrency(total_ram_gb=32.0, is_8k=False, max_cores=16)
    print(f"32GB 筆電在 4K 模式下的安全平行緒數: {concur_32g_4k} 緒")
    assert concur_32g_4k >= 12, f"32GB 筆電跑 4K 應允許高平行緒 (實際: {concur_32g_4k})"

    # 模擬 2：16GB 輕薄筆電 (8 核心)
    concur_16g_8k = calculate_safe_concurrency(total_ram_gb=16.0, is_8k=True, max_cores=8)
    print(f"16GB 筆電在 8K 模式下的安全平行緒數: {concur_16g_8k} 緒")
    assert 2 <= concur_16g_8k <= 4, f"16GB 筆電跑 8K 應保守在 2~4 緒 (實際: {concur_16g_8k})"

    # 模擬 3：64GB/128GB 高階桌機 (28 核心)
    concur_64g_8k = calculate_safe_concurrency(total_ram_gb=64.0, is_8k=True, max_cores=28)
    print(f"64GB 桌機在 8K 模式下的安全平行緒數: {concur_64g_8k} 緒")
    assert concur_64g_8k >= 14, f"64GB 桌機跑 8K 應允許 14 緒以上 (實際: {concur_64g_8k})"

    print("[PASS] 各硬體規格記憶體安全計算邏輯完全正確！")


if __name__ == "__main__":
    test_memory_detection()
    test_concurrency_calculation()
    print("\n[ALL PASS] 記憶體防護與 SSD 保護測試全數通過！")
