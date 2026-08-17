import os
import re
import shutil
import subprocess
import sys

# On Windows PyInstaller uses ';' as the --add-data separator, elsewhere ':'
SEP = ";" if os.name == "nt" else ":"
ROOT = os.path.dirname(os.path.abspath(__file__))


def read_version() -> str:
    """Read the version from app/version.py without importing the app.

    Parsing the file (instead of importing) keeps the build script usable
    in a bare environment where runtime dependencies are not installed yet.
    """
    path = os.path.join(ROOT, "app", "version.py")
    with open(path, encoding="utf-8") as f:
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', f.read())
    if not match:
        raise RuntimeError("Could not find __version__ in app/version.py")
    return match.group(1)


def version_tuple(version: str, length: int = 4) -> tuple:
    """'1.2.3' -> (1, 2, 3, 0); tolerant of suffixes like '1.2.3-beta'."""
    parts = []
    for piece in version.split("."):
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group()) if digits else 0)
    while len(parts) < length:
        parts.append(0)
    return tuple(parts[:length])


def write_windows_version_info(version: str) -> str:
    """Generate a PyInstaller --version-file so the .exe carries metadata.

    The resulting file lets Windows Explorer show FileDescription,
    FileVersion, ProductName etc. under Properties -> Details.
    """
    vt = version_tuple(version)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vt},
    prodvers={vt},
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileDescription', 'TikTok OBS Live Integration Server'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'TikTokOBS'),
        StringStruct('LegalCopyright', 'TikTObs'),
        StringStruct('OriginalFilename', 'TikTokOBS.exe'),
        StringStruct('ProductName', 'TikTokOBS'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = os.path.join(ROOT, "build", "version_info.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def build():
    version = read_version()
    print("==================================================")
    print("      Building TikTok OBS Standalone Executable   ")
    print(f"      Version: {version:<36}")
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

    # Windows-only: embed version metadata into the executable
    version_args = []
    if os.name == "nt":
        info_path = write_windows_version_info(version)
        version_args = [f"--version-file={info_path}"]

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
        *version_args,
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

    # 4. Produce the versioned artifact alongside the plain one
    base_name = "TikTokOBS.exe" if os.name == "nt" else "TikTokOBS"
    ext = ".exe" if os.name == "nt" else ""
    src = os.path.join(ROOT, "dist", base_name)
    versioned = os.path.join(ROOT, "dist", f"TikTokOBS-{version}{ext}")
    shutil.copy2(src, versioned)

    print("\n==================================================")
    print(" BUILD SUCCESSFUL!")
    print(f" Versioned : dist/{os.path.basename(versioned)}")
    print(f" Plain     : dist/{base_name}")
    print("==================================================")


if __name__ == "__main__":
    build()
