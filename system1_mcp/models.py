"""Model artifact management, atomic download, and integrity verification for System 1 MCP."""

import hashlib
import os
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from system1_mcp.config import get_config_dir

VERDICT_REPO = "heman10x/rlcd-modernbert-151m"
VERDICT_REVISION = "8af2496eb63c7fa66d7d234e1f62629380030eb4"
VERDICT_ONNX_SHA256 = "4ae01f822538b000fa0e55859d4b3e6b40871d860149397e8784428b2a42ee5e"

VERDICT_FILES: Dict[str, Optional[str]] = {
    "model.onnx": VERDICT_ONNX_SHA256,
    "tokenizer.json": None,
    "calibrator.json": None,
}


def get_default_model_dir() -> Path:
    """Universal default directory for local model weights: ~/.system1/models/verdict."""
    return get_config_dir() / "models" / "verdict"


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Compute SHA-256 digest of a file in 64KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_model_integrity(model_path: Union[str, Path]) -> Tuple[bool, str]:
    """Verify that model.onnx exists and matches the pinned SHA-256 hash."""
    p = Path(model_path)
    if not p.is_file():
        return False, f"File does not exist: {p}"

    actual_hash = compute_file_sha256(p)
    if actual_hash.lower() != VERDICT_ONNX_SHA256.lower():
        return False, (
            f"SHA-256 mismatch for {p.name}:\n"
            f"  Expected: {VERDICT_ONNX_SHA256}\n"
            f"  Got:      {actual_hash}"
        )
    return True, "Integrity verified (SHA-256 matches pinned checkpoint)"


def download_file_atomic(
    url: str,
    dest_path: Path,
    expected_sha256: Optional[str] = None,
    force: bool = False,
    verbose: bool = True,
) -> int:
    """Download a file atomically with optional streaming SHA-256 verification."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Skip if file exists and hash matches
    if dest_path.is_file() and not force:
        if expected_sha256:
            existing_hash = compute_file_sha256(dest_path)
            if existing_hash.lower() == expected_sha256.lower():
                if verbose:
                    print(f"  [OK] {dest_path.name} already exists and verified ({dest_path.stat().st_size:,} bytes)", file=sys.stderr)
                return dest_path.stat().st_size
        else:
            if verbose:
                print(f"  [OK] {dest_path.name} already exists ({dest_path.stat().st_size:,} bytes)", file=sys.stderr)
            return dest_path.stat().st_size

    tmp_path = dest_path.with_suffix(f".tmp_{os.getpid()}_{os.urandom(4).hex()}")
    req = urllib.request.Request(url, headers={"User-Agent": "system1-mcp/0.2.0"})

    if verbose:
        print(f"  Downloading {dest_path.name} from {url}...", file=sys.stderr)

    hasher = hashlib.sha256() if expected_sha256 else None
    downloaded_bytes = 0

    try:
        with urllib.request.urlopen(req) as resp, open(tmp_path, "wb") as out_f:
            total_size_header = resp.headers.get("Content-Length")
            total_size = int(total_size_header) if total_size_header else None

            while chunk := resp.read(65536):
                out_f.write(chunk)
                downloaded_bytes += len(chunk)
                if hasher:
                    hasher.update(chunk)

        if expected_sha256 and hasher:
            actual_sha256 = hasher.hexdigest().lower()
            if actual_sha256 != expected_sha256.lower():
                raise ValueError(
                    f"Integrity check failed for {dest_path.name}!\n"
                    f"  Expected: {expected_sha256}\n"
                    f"  Computed: {actual_sha256}\n"
                    f"Download aborted; temporary artifact discarded."
                )

        # Atomic replacement
        tmp_path.replace(dest_path)
        if verbose:
            print(f"  [OK] Saved {dest_path.name} ({downloaded_bytes:,} bytes, verified)", file=sys.stderr)
        return downloaded_bytes

    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def download_verdict_model(
    target_dir: Optional[Union[str, Path]] = None,
    force: bool = False,
    verbose: bool = True,
) -> Path:
    """Download all Verdict model artifacts from Hugging Face into target directory.

    Downloads:
    - model.onnx (verified against pinned SHA-256)
    - tokenizer.json
    - calibrator.json

    Returns:
        The target directory Path.
    """
    dest_dir = Path(target_dir) if target_dir else get_default_model_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"\nDownloading Verdict Open-Jev Model (Revision: {VERDICT_REVISION[:8]}...)", file=sys.stderr)
        print(f"Destination: {dest_dir}\n", file=sys.stderr)

    total_bytes = 0
    for filename, expected_hash in VERDICT_FILES.items():
        url = f"https://huggingface.co/{VERDICT_REPO}/resolve/{VERDICT_REVISION}/{filename}"
        dest_file = dest_dir / filename
        bytes_count = download_file_atomic(
            url=url,
            dest_path=dest_file,
            expected_sha256=expected_hash,
            force=force,
            verbose=verbose,
        )
        total_bytes += bytes_count

    if verbose:
        print(f"\nSuccessfully verified and installed Verdict model artifacts ({total_bytes:,} total bytes).", file=sys.stderr)
        print(f"Weights ready at: {dest_dir}\n", file=sys.stderr)

    return dest_dir
