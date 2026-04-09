#!/usr/bin/env python3
"""
Rename and reorganize the outlines/ folder to kebab-case with lowercase extensions.

Run with --dry-run (default) to preview, then --apply to execute.
"""

import os
import re
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent / "outlines"
REF_DIR = BASE / "_reference"

# ── Helpers ───────────────────────────────────────────


def to_kebab(name: str) -> str:
    """Convert a filename/folder name to kebab-case."""
    # Normalize multiple spaces / weird spacing around dashes
    name = re.sub(r"\s+", " ", name.strip())
    # Fix "XD -9" → "XD-9"
    name = re.sub(r"\s+-", "-", name)
    name = re.sub(r"-\s+", "-", name)
    # Replace spaces with dashes, lowercase everything
    name = name.replace(" ", "-").lower()
    # Collapse multiple dashes
    name = re.sub(r"-+", "-", name)
    return name


def kebab_ext(path: Path) -> str:
    """Return the extension lowercased."""
    return path.suffix.lower()


REFERENCE_EXTS = {".jpg", ".jpeg", ".png", ".csp", ".bmp", ".tiff"}
JOB_EXTS = {".background", ".outline", ".lgf"}


def is_reference_file(p: Path) -> bool:
    return p.suffix.lower() in REFERENCE_EXTS


def is_job_component(p: Path) -> bool:
    return p.suffix.lower() in JOB_EXTS


# ── Plan generation ───────────────────────────────────


def plan_moves():
    """Return a list of (src, dst) tuples for all renames/moves."""
    moves = []

    if not BASE.exists():
        print(f"ERROR: {BASE} does not exist")
        sys.exit(1)

    # Walk bottom-up so we rename files before their parent dirs
    # First pass: collect all files and plan their new names
    file_moves = []
    dir_renames = []
    ref_moves = []

    for root, dirs, files in os.walk(BASE, topdown=False):
        root_path = Path(root)
        rel = root_path.relative_to(BASE)

        # Skip .DS_Store
        for f in files:
            src = root_path / f
            if f == ".DS_Store":
                continue

            # Reference images → move to _reference/
            if is_reference_file(src):
                # Build a kebab subfolder name from the current path
                ref_subdir = to_kebab(str(rel).replace("/", "--"))
                dst = REF_DIR / ref_subdir / (to_kebab(Path(f).stem) + kebab_ext(src))
                ref_moves.append((src, dst))
                continue

            # SVG test outputs in outlines (not actual outlines) — move to _reference
            if src.suffix.lower() == ".svg":
                ref_subdir = to_kebab(str(rel).replace("/", "--"))
                dst = REF_DIR / ref_subdir / (to_kebab(Path(f).stem) + ".svg")
                ref_moves.append((src, dst))
                continue

            # Build the new kebab path
            new_parts = []
            for part in rel.parts:
                new_parts.append(to_kebab(part))
            new_dir = BASE / Path(*new_parts) if new_parts else BASE

            # Rename the file itself
            stem = Path(f).stem
            ext = kebab_ext(src)
            new_name = to_kebab(stem) + ext

            dst = new_dir / new_name
            if src != dst:
                file_moves.append((src, dst))

    # Directory renames (bottom-up to avoid conflicts)
    # We need to collect unique directories that need renaming
    seen_dirs = set()
    for root, dirs, files in os.walk(BASE, topdown=False):
        root_path = Path(root)
        if root_path == BASE:
            continue
        rel = root_path.relative_to(BASE)
        new_parts = [to_kebab(part) for part in rel.parts]
        new_dir = BASE / Path(*new_parts)
        if root_path != new_dir and root_path not in seen_dirs:
            dir_renames.append((root_path, new_dir))
            seen_dirs.add(root_path)

    return ref_moves, file_moves, dir_renames


def print_plan(ref_moves, file_moves, dir_renames):
    """Print a summary of planned changes."""
    print("=" * 70)
    print("OUTLINES REORGANIZATION PLAN")
    print("=" * 70)

    if ref_moves:
        print(f"\n── Reference files to move ({len(ref_moves)}) ──")
        for src, dst in ref_moves:
            print(f"  {src.relative_to(BASE)}")
            print(f"    → {dst.relative_to(BASE)}")

    renamed = [
        (s, d)
        for s, d in file_moves
        if s.parent == d.parent
        or s.relative_to(BASE).parts[:-1] == d.relative_to(BASE).parts[:-1]
    ]
    if renamed:
        print(f"\n── Files to rename ({len(file_moves)}) ──")
        # Group by directory for readability
        shown = 0
        for src, dst in file_moves:
            if shown < 30:
                print(f"  {src.relative_to(BASE)}")
                print(f"    → {dst.relative_to(BASE)}")
                shown += 1
        if len(file_moves) > 30:
            print(f"  ... and {len(file_moves) - 30} more")

    if dir_renames:
        print(f"\n── Directories to rename ({len(dir_renames)}) ──")
        for src, dst in sorted(dir_renames, key=lambda x: len(str(x[0])), reverse=True):
            print(f"  {src.relative_to(BASE)}")
            print(f"    → {dst.relative_to(BASE)}")

    total = len(ref_moves) + len(file_moves) + len(dir_renames)
    print(f"\nTotal operations: {total}")


def execute(ref_moves, file_moves, dir_renames):
    """Execute all moves/renames."""
    errors = []

    # 1. Move reference files first
    for src, dst in ref_moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except Exception as e:
            errors.append(f"REF {src} → {dst}: {e}")

    # 2. Rename files (in their current locations)
    for src, dst in file_moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except Exception as e:
            errors.append(f"FILE {src} → {dst}: {e}")

    # 3. Rename directories bottom-up (deepest first)
    # Sort by depth descending so children are renamed before parents
    dir_renames_sorted = sorted(
        dir_renames, key=lambda x: len(x[0].parts), reverse=True
    )
    for src, dst in dir_renames_sorted:
        try:
            if src.exists():
                # If destination already exists (because files were moved there),
                # move remaining contents
                if dst.exists():
                    for item in src.iterdir():
                        shutil.move(str(item), str(dst / item.name))
                    src.rmdir()
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
        except Exception as e:
            errors.append(f"DIR {src} → {dst}: {e}")

    # 4. Clean up empty directories
    for root, dirs, files in os.walk(BASE, topdown=False):
        root_path = Path(root)
        if root_path == BASE:
            continue
        remaining = [f for f in os.listdir(root_path) if f != ".DS_Store"]
        if not remaining:
            # Remove .DS_Store if it's the only thing left
            ds = root_path / ".DS_Store"
            if ds.exists():
                ds.unlink()
            try:
                root_path.rmdir()
            except OSError:
                pass

    if errors:
        print(f"\n{len(errors)} errors:")
        for e in errors:
            print(f"  {e}")
    else:
        print("All operations completed successfully.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"

    ref_moves, file_moves, dir_renames = plan_moves()
    print_plan(ref_moves, file_moves, dir_renames)

    if mode == "--apply":
        print("\nExecuting...")
        execute(ref_moves, file_moves, dir_renames)
    else:
        print("\nDry run — no changes made. Use --apply to execute.")
