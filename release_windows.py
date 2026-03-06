#!/usr/bin/env python3

import argparse
import hashlib
import json
import sys
from pathlib import Path


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
            existing_package_files.append(entry)
        else:
            missing_package_files.append(rel)

    client_manifest = {
        "revision": args.revision,
        "version": args.version,
        "files": existing_package_files,
        "executable": package_payload.get("executable", "bin/client_launcher.exe"),
        "generation": args.generation,
        "variant": args.variant,
    }

    assets_manifest = {
        "version": args.revision,
        "files": assets_payload["files"],
    }

    version_manifest = {
        "revision": args.revision,
        "version": args.version,
        "generation": args.generation,
        "variant": args.variant,
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

    for candidate in files_to_hash:
        if candidate.exists() and candidate.is_file():
            generated_sha.append(write_sha256(candidate))

    print("Release files generated:")
    print(f"- {client_windows_path.name}")
    print(f"- {assets_windows_path.name}")
    print(f"- {version_path.name}")
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
