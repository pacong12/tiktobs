"""Single source of truth for the application version.

The build script (build_exe.py) reads this file to:
  1. name the executable  -> dist/TikTokOBS-<version>.exe
  2. embed Windows file metadata (Properties -> Details)

Bump the version here before building a release. Follow semver:
  MAJOR.MINOR.PATCH  (e.g. 1.0.0 -> 1.1.0 for features, 1.1.1 for fixes)
"""

__version__ = "1.2.5"


def get_version() -> str:
    return __version__
