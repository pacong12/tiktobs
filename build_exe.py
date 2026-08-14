import os
import subprocess
import sys

# On Windows PyInstaller uses ';' as the --add-data separator, elsewhere ':'
SEP = ";" if os.name == "nt" else ":"


def build():
    print("==================================================")
    print("      Building TikTok OBS Standalone Executable   ")
    print("==================================================")

    # 1. Install PyInstaller if not present
    print("Checking PyInstaller...")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )

    # 2. Make sure runtime dependencies are present before bundling
    print("Ensuring runtime dependencies are installed...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        check=True,
    )

    icon_args = ["--icon=app.ico"] if os.path.exists("app.ico") else []

    # 3. PyInstaller command arguments
    # --onefile: Packages everything into a single TikTokOBS executable
    # --add-data: Embeds static assets (HTML, CSS, JS, Sounds) inside the executable
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=TikTokOBS",
        "--onefile",
        "--noconfirm",
        "--clean",
        *icon_args,
        f"--add-data=static{SEP}static",
        "--collect-all=TikTokLive",
        "--collect-submodules=uvicorn",
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
        "--hidden-import=multipart",
        "--hidden-import=httpx",
        "--hidden-import=websockets",
        "--hidden-import=app.main",
        "run_app.py",
    ]

    print("\nRunning PyInstaller build process...")
    subprocess.run(cmd, check=True)

    exe_name = "TikTokOBS.exe" if os.name == "nt" else "TikTokOBS"
    print("\n==================================================")
    print(" BUILD SUCCESSFUL!")
    print(f" Executable file path: dist/{exe_name}")
    print("==================================================")


if __name__ == "__main__":
    build()
