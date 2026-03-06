#!/usr/bin/env python3

import argparse
import hashlib
import json
import sys
from pathlib import Path
import zipfile

BUNDLE_PART_MAX_BYTES = 80 * 1024 * 1024


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_sha256(path: Path):
    digest = sha256_file(path)
    output = path.with_suffix(path.suffix + ".sha256")
    output.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return output


def build_assets_bundles(root: Path) -> list[Path]:
    assets_dir = root / "assets"
    if not assets_dir.is_dir():
        raise FileNotFoundError(f"Missing assets directory: {assets_dir}")

    files = [file_path for file_path in sorted(assets_dir.rglob("*")) if file_path.is_file()]
    if not files:
        raise RuntimeError("No files found to build assets bundle")

    parts: list[list[Path]] = []
    current_part: list[Path] = []
    current_size = 0

    for file_path in files:
        file_size = file_path.stat().st_size
        if current_part and current_size + file_size > BUNDLE_PART_MAX_BYTES:
            parts.append(current_part)
            current_part = []
            current_size = 0

        current_part.append(file_path)
        current_size += file_size

    if current_part:
        parts.append(current_part)

    bundle_paths: list[Path] = []
    for index, part_files in enumerate(parts, start=1):
        bundle_path = root / f"assets.bundle.part{index}.zip"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for file_path in part_files:
                arcname = file_path.relative_to(root).as_posix()
                archive.write(file_path, arcname=arcname)
        bundle_paths.append(bundle_path)

    return bundle_paths


def normalize_entry(entry: dict, root: Path):
    normalized = dict(entry)
    rel = normalized.get("url")
    if not rel:
        return normalized

    file_path = root / rel
    if not file_path.is_file():
        return normalized

    packed_size = file_path.stat().st_size
    packed_hash = sha256_file(file_path)

    normalized["packedsize"] = packed_size
    normalized["packedhash"] = packed_hash

    if not normalized.get("unpackedhash"):
        normalized["unpackedhash"] = packed_hash
    if not normalized.get("unpackedsize"):
        normalized["unpackedsize"] = packed_size

    return normalized


def choose_executable(existing_package_files: list[dict], configured: str):
    localfiles = {entry.get("localfile") for entry in existing_package_files}
    if configured and configured in localfiles:
        return configured

    executable_marked = [
        entry.get("localfile")
        for entry in existing_package_files
        if entry.get("executable") is True and entry.get("localfile") in localfiles
    ]
    if executable_marked:
        return executable_marked[0]

    if "bin/client.exe" in localfiles:
        return "bin/client.exe"

    exe_candidates = [
        entry.get("localfile")
        for entry in existing_package_files
        if isinstance(entry.get("localfile"), str) and entry.get("localfile", "").endswith(".exe")
    ]
    if exe_candidates:
        return exe_candidates[0]

    return configured


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Windows release manifests and checksum files for OTBaiak launcher/client."
    )
    parser.add_argument("--generation", required=True, help="Release generation identifier, e.g. otbaiak-v1.2")
    parser.add_argument("--revision", required=True, type=int, help="Numeric revision used by launcher")
    parser.add_argument("--version", required=True, help="Display version, e.g. 15.11.x")
    parser.add_argument("--variant", default="otbaiak", help="Release variant (default: otbaiak)")
    parser.add_argument("--root", default=".", help="Client package root folder (default: current directory)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    package_path = root / "package.json"
    assets_path = root / "assets.json"

    if not package_path.exists():
        print(f"ERROR: missing file {package_path}", file=sys.stderr)
        return 1
    if not assets_path.exists():
        print(f"ERROR: missing file {assets_path}", file=sys.stderr)
        return 1

    package_payload = read_json(package_path)
    assets_payload = read_json(assets_path)

    if "files" not in package_payload or not isinstance(package_payload["files"], list):
        print("ERROR: package.json is missing a valid 'files' array", file=sys.stderr)
        return 1
    if "files" not in assets_payload or not isinstance(assets_payload["files"], list):
        print("ERROR: assets.json is missing a valid 'files' array", file=sys.stderr)
        return 1

    package_files = package_payload["files"]
    existing_package_files = []
    missing_package_files = []

    for entry in package_files:
        rel = entry.get("url")
        if not rel:
            continue
        if (root / rel).is_file():
            existing_package_files.append(normalize_entry(entry, root))
        else:
            missing_package_files.append(rel)

    if not existing_package_files:
        print("ERROR: no package entries found with files present on disk", file=sys.stderr)
        return 1

    configured_executable = package_payload.get("executable", "bin/client_launcher.exe")
    executable = choose_executable(existing_package_files, configured_executable)
    if not executable or executable not in {entry.get("localfile") for entry in existing_package_files}:
        print(
            f"ERROR: could not resolve executable. Configured '{configured_executable}' is not available.",
            file=sys.stderr,
        )
        return 1

    normalized_assets_files = [normalize_entry(entry, root) for entry in assets_payload["files"]]

    client_manifest = {
        "revision": args.revision,
        "version": args.version,
        "files": existing_package_files,
        "executable": executable,
        "generation": args.generation,
        "variant": args.variant,
    }

    assets_manifest = {
        "version": args.revision,
        "files": normalized_assets_files,
    }

    assets_bundle_paths = build_assets_bundles(root)
    assets_bundle_urls = [path.name for path in assets_bundle_paths]
    assets_bundle_shas = [sha256_file(path) for path in assets_bundle_paths]

    version_manifest = {
        "revision": args.revision,
        "version": args.version,
        "generation": args.generation,
        "variant": args.variant,
        "assets_bundle_urls": assets_bundle_urls,
        "assets_bundle_sha256_list": assets_bundle_shas,
        "assets_bundle_url": assets_bundle_urls[0],
        "assets_bundle_sha256": assets_bundle_shas[0],
    }

    client_windows_path = root / "client.windows.json"
    assets_windows_path = root / "assets.windows.json"
    version_path = root / "version.json"

    write_json(client_windows_path, client_manifest)
    write_json(assets_windows_path, assets_manifest)
    write_json(version_path, version_manifest)

    generated_sha = []
    files_to_hash = [
        root / "OTBaiak.exe",
        root / "Slender.exe",
        root / "assets.json",
        root / "assets.windows.json",
        root / "client.windows.json",
        root / "version.json",
    ]

    files_to_hash.extend(assets_bundle_paths)

    for candidate in files_to_hash:
        if candidate.exists() and candidate.is_file():
            generated_sha.append(write_sha256(candidate))

    print("Release files generated:")
    print(f"- {client_windows_path.name}")
    print(f"- {assets_windows_path.name}")
    print(f"- {version_path.name}")
    print("- assets bundles:")
    for bundle_path in assets_bundle_paths:
        print(f"  * {bundle_path.name}")
    print(f"- executable: {executable}")
    print(f"- client.windows.json entries: {len(existing_package_files)}")
    if missing_package_files:
        print(f"- skipped missing package entries: {len(missing_package_files)}")
        for rel in missing_package_files:
            print(f"  * {rel}")
    if generated_sha:
        print("SHA256 files generated:")
        for item in generated_sha:
            print(f"- {item.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
