import subprocess
import sys

def build():
    print("==================================================")
    print("      Building TikTok OBS Standalone Executable   ")
    print("==================================================")
    
    # 1. Install PyInstaller if not present
    print("Checking PyInstaller...")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.run(["uv", "pip", "install", "pyinstaller"], check=False)

    # 2. PyInstaller command arguments
    # --onefile: Packages everything into a single TikTokOBS.exe
    # --add-data: Embeds static assets (HTML, CSS, JS, Sounds) inside the executable
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=TikTokOBS",
        "--onefile",
        "--icon=app.ico",
        "--add-data=static;static",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=aiosqlite",
        "run_app.py"
    ]
    
    print("\nRunning PyInstaller build process...")
    subprocess.run(cmd, check=True)
    
    print("\n==================================================")
    print(" BUILD SUCCESSFUL!")
    print(" Executable file path: dist/TikTokOBS.exe")
    print("==================================================")

if __name__ == "__main__":
    build()
