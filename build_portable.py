"""
一鍵自動打包腳本 - 製作 Windows 綠色免安裝可攜資料夾 (Portable Folder)
包含：
1. Python + PyQt6 完整執行環境
2. 內建全功能可攜式 FFmpeg / FFprobe (支援 Intel QSV / NVIDIA NVENC / AMD AMF)
3. 免安裝、免 Python、免環境變數，解壓即可運作！
"""

import os
import sys
import shutil
import subprocess

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def build_portable():
    print("=" * 60)
    print("[啟動] 開始製作 PhotoToVideo 綠色免安裝可攜資料夾...")
    print("=" * 60)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")
    output_app_dir = os.path.join(dist_dir, "PhotoToVideo")

    # 1. 檢查 bin/ffmpeg.exe 與 bin/ffprobe.exe 是否存在
    local_ffmpeg = os.path.join(root_dir, "bin", "ffmpeg.exe")
    local_ffprobe = os.path.join(root_dir, "bin", "ffprobe.exe")
    if not os.path.exists(local_ffmpeg) or not os.path.exists(local_ffprobe):
        print("[錯誤] 找不到 bin/ffmpeg.exe 或 bin/ffprobe.exe！")
        return False

    # 2. 徹底清理舊的輸出目錄與快取
    if os.path.exists(dist_dir):
        print("[清理] 清理舊的 dist 輸出目錄...")
        subprocess.run(["powershell", "-Command", "Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue"], cwd=root_dir)
    if os.path.exists(build_dir):
        subprocess.run(["powershell", "-Command", "Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue"], cwd=root_dir)

    # 3. 組裝 PyInstaller 指令
    pyinstaller_exe = os.path.join(
        os.path.dirname(sys.executable), "Scripts", "pyinstaller.exe"
    )
    if not os.path.exists(pyinstaller_exe):
        pyinstaller_exe = "pyinstaller"

    cmd = [
        pyinstaller_exe,
        "--onedir",
        "--noconsole",
        "--name", "PhotoToVideo",
        "--noconfirm",
        "--add-binary", f"{local_ffmpeg};bin",
        "--add-binary", f"{local_ffprobe};bin",
        "--hidden-import", "PyQt6",
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "PIL",
        "--hidden-import", "piexif",
        "app.py"
    ]

    print(f"[打包] 正在執行 PyInstaller 編譯封裝：{' '.join(cmd)}")
    ret = subprocess.run(cmd, cwd=root_dir)
    if ret.returncode != 0:
        print("[錯誤] PyInstaller 打包失敗！")
        return False

    # 4. 確保輸出目錄下具有可攜式 bin/ (包含 ffmpeg.exe 與 ffprobe.exe)
    target_bin_dir = os.path.join(output_app_dir, "bin")
    os.makedirs(target_bin_dir, exist_ok=True)
    target_ff = os.path.join(target_bin_dir, "ffmpeg.exe")
    target_fp = os.path.join(target_bin_dir, "ffprobe.exe")
    if not os.path.exists(target_ff):
        print(f"[複製] 正在複製內建可攜式 FFmpeg 引擎至：{target_bin_dir}")
        shutil.copy2(local_ffmpeg, target_ff)
    if not os.path.exists(target_fp):
        shutil.copy2(local_ffprobe, target_fp)

    # 5. 建立使用說明文字檔
    readme_path = os.path.join(output_app_dir, "使用說明.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("=" * 50 + "\n")
        f.write("相簿轉 8K/4K YouTube 極致備份影片合成工具\n")
        f.write("【綠色免安裝可攜版】\n")
        f.write("=" * 50 + "\n\n")
        f.write("【啟動方式】\n")
        f.write("直接雙擊執行「PhotoToVideo.exe」即可開啟圖形化操作介面。\n\n")
        f.write("【特性說明】\n")
        f.write("1. 零依賴：本資料夾已完整內建 Python 執行環境與 Intel/NVIDIA/AMD 頂級硬體加速引擎。\n")
        f.write("2. 免設定：不需要安裝 Python，也不需要手動設定任何 FFmpeg 環境變數。\n")
        f.write("3. 可攜帶：整包資料夾可自由複製至隨身碟或隨身硬碟，在任何 Windows 10/11 電腦隨插即用。\n")

    # 6. 驗證產出結果
    exe_path = os.path.join(output_app_dir, "PhotoToVideo.exe")
    if not os.path.exists(exe_path):
        print("[錯誤] 找不到產出的主執行檔 PhotoToVideo.exe！")
        return False

    print("\n[驗證] 正在驗證產出的執行檔 (無 GUI 測試模式)...")
    try:
        test_run = subprocess.run([exe_path, "--test"], capture_output=True, text=True)
        print(f"測試模式輸出：{test_run.stdout.strip()}")
        if test_run.returncode == 0:
            print("[成功] 執行檔驗證成功！可於一般 Windows 電腦開箱即用！")
        else:
            print(f"[警告] 執行檔測試回傳碼：{test_run.returncode}，錯誤：{test_run.stderr}")
    except OSError as e:
        if "4551" in str(e) or "封鎖" in str(e):
            print("[安全性提示] 偵測到本機啟用了 Windows 11 智慧型應用程式控制 (Smart App Control)。")
            print("             此為 Windows 對新編譯二進位檔的常規提示，使用者於檔案總管雙擊時點選『其他資訊 ➡️ 仍要執行』即可正常運作！")
        else:
            print(f"[警告] 執行檔測試時遇到異常：{e}")

    # 建立啟動捷徑批次檔
    launcher_bat = os.path.join(output_app_dir, "啟動_PhotoToVideo.bat")
    with open(launcher_bat, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("chcp 65001 >nul\n")
        f.write('start "" "%~dp0PhotoToVideo.exe"\n')

    print("\n" + "=" * 60)
    print(f"[完成] 綠色免安裝資料夾製作完成！")
    print(f"輸出完整路徑：{output_app_dir}")
    print(f"主程式位置：{exe_path}")
    print(f"便捷啟動腳本：{launcher_bat}")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = build_portable()
    sys.exit(0 if success else 1)
