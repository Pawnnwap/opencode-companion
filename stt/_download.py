"""Download Paraformer-zh int8 models from HuggingFace."""

import os
import sys
import urllib.request
from pathlib import Path

if getattr(sys, "frozen", False):
    # bundled with the app (PyInstaller); for onedir this is <app>/_internal
    _base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    MODEL_DIR = _base / "stt" / "models"
else:
    MODEL_DIR = Path(__file__).parent / "models"

MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2"
)

ARCHIVE_NAME = "sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2"
EXTRACTED_DIR = "sherpa-onnx-paraformer-zh-int8-2025-10-07"

# Known good archive size (bytes) — if the downloaded file is smaller
# the download was interrupted and we should re-fetch.
EXPECTED_SIZE = 106_000_000  # ~106 MB


def _progress_hook(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb_down = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        sys.stdout.write(f"\r  Downloading: {pct}% ({mb_down:.1f}/{mb_total:.1f} MB)")
        sys.stdout.flush()


def _extract(archive_path: Path) -> bool:
    """Extract the tar.bz2 archive. Returns True on success."""
    import tarfile
    try:
        with tarfile.open(str(archive_path), "r:bz2") as tar:
            tar.extractall(str(MODEL_DIR))
        return True
    except (EOFError, tarfile.ReadError, OSError) as e:
        print(f"\n  Extraction failed: {e}")
        print("  Archive appears corrupted — will delete and re-download.")
        archive_path.unlink(missing_ok=True)
        return False


def download_models(force: bool = False) -> Path:
    """Download Paraformer-zh int8 models if not present.

    Returns the path to the model directory containing model.int8.onnx and tokens.txt.
    """
    model_file = MODEL_DIR / "model.int8.onnx"
    tokens_file = MODEL_DIR / "tokens.txt"
    if model_file.exists() and tokens_file.exists() and not force:
        print(f"Models already present at {MODEL_DIR}")
        return MODEL_DIR

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    archive_path = MODEL_DIR / ARCHIVE_NAME

    # If the archive already exists, try extracting it first.
    # On failure (corrupted partial download), delete and re-download.
    if archive_path.exists():
        size = archive_path.stat().st_size
        if size < EXPECTED_SIZE:
            print(f"  Archive is incomplete ({size / 1024 / 1024:.1f} MB < ~106 MB expected).")
            print("  Deleting and re-downloading...")
            archive_path.unlink()
        elif not _extract(archive_path):
            # extraction failed, archive was deleted by _extract
            pass

    if not archive_path.exists():
        print(f"Downloading Paraformer-zh int8 models...")
        print(f"  URL: {MODEL_URL}")
        urllib.request.urlretrieve(MODEL_URL, str(archive_path), _progress_hook)
        print()
        # verify download size
        size = archive_path.stat().st_size
        print(f"  Downloaded: {size / 1024 / 1024:.1f} MB")
        if size < EXPECTED_SIZE:
            print(f"  WARNING: file may be incomplete (expected ~106 MB).")
            print(f"  Attempting extraction anyway...")

    print("Extracting...")
    if not _extract(archive_path):
        raise RuntimeError(
            "Failed to download or extract STT models. "
            "Try again or download manually from:\n  " + MODEL_URL
        )

    extracted = MODEL_DIR / EXTRACTED_DIR
    if extracted.exists():
        import shutil
        for item in extracted.iterdir():
            dest = MODEL_DIR / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(str(dest))
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        extracted.rmdir()

    archive_path.unlink(missing_ok=True)

    print(f"Models ready at {MODEL_DIR}")
    return MODEL_DIR


if __name__ == "__main__":
    download_models()
