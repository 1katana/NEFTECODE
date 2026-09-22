"""Build a small, explicit source bundle for the Python orchestrator."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import os
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "handoff" / "neftecode_optimizer_for_polina.zip"
ARCHIVE_ROOT = "neftecode_optimizer"

ROOT_FILES = (
    "pyproject.toml",
    "README.md",
    "POLINA_HANDOFF.md",
)
DIRECTORY_FILES = {
    "optimization": ("*.py", "*.yaml"),
    "examples": ("*.json", "*.yaml"),
    "docs": ("*.md",),
    "tests": ("test_*.py",),
    "scripts": ("build_handoff.py",),
}


def source_files() -> list[Path]:
    """Return only reviewed, portable project files; never traverse archives/data."""
    files = [ROOT / name for name in ROOT_FILES]
    for directory, patterns in DIRECTORY_FILES.items():
        base = ROOT / directory
        for pattern in patterns:
            files.extend(base.glob(pattern))
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing handoff files: {', '.join(missing)}")
    return sorted(set(files), key=lambda path: path.relative_to(ROOT).as_posix())


def build() -> tuple[Path, int]:
    files = source_files()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".optimizer-handoff-", suffix=".zip", dir=OUTPUT.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                archive.write(path, f"{ARCHIVE_ROOT}/{relative}")
        with ZipFile(temporary_path) as archive:
            failed_member = archive.testzip()
            if failed_member is not None:
                raise ValueError(f"Corrupted ZIP member: {failed_member}")
        os.replace(temporary_path, OUTPUT)
    finally:
        temporary_path.unlink(missing_ok=True)
    return OUTPUT, len(files)


if __name__ == "__main__":
    output, count = build()
    print(f"Created {output} with {count} reviewed files ({output.stat().st_size} bytes)")
