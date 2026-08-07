import subprocess
import sys

def build():
    print("==================================================")
    print("      Building TikTok OBS Standalone Executable   ")
    print("==================================================")
    
    # 1. Install PyInstaller if not present
    print("Checking / Installing PyInstaller...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # 2. PyInstaller command arguments
    # --onefile: Packages everything into a single TikTokOBS.exe
    # --add-data: Embeds static assets (HTML, CSS, JS, Sounds) inside the executable
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=TikTokOBS",
        "--onefile",
        "--add-data=static;static",
        "run_app.py"
    ]
    
    print("\nRunning PyInstaller build process...")
    subprocess.run(cmd, check=True)
    
    print("\n==================================================")
    print(" 🎉 BUILD SUCCESSFUL!")
    print(" Executable file path: dist/TikTokOBS.exe")
    print("==================================================")

if __name__ == "__main__":
    build()
