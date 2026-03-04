#!/usr/bin/env python3
import argparse
import hashlib
import json
import lzma
from pathlib import Path


def sha256_and_size(path: Path):
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


def unpacked_sha256_and_size_from_lzma(path: Path):
    h = hashlib.sha256()
    size = 0
    with lzma.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


def ensure_lzma_from_local(root: Path, url_path: str, localfile: str):
    url_file = root / url_path
    if url_file.exists():
        return
    if not url_path.endswith(".lzma"):
        raise FileNotFoundError(f"Missing payload file: {url_path}")

    local = root / localfile
    if not local.exists():
        raise FileNotFoundError(f"Missing local file to build lzma: {localfile} -> {url_path}")

    url_file.parent.mkdir(parents=True, exist_ok=True)
    data = local.read_bytes()
    compressed = lzma.compress(data, format=lzma.FORMAT_ALONE)
    url_file.write_bytes(compressed)


def update_manifest(root: Path, manifest_name: str):
    manifest_path = root / manifest_name
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    updated_fields = 0

    for entry in data.get("files", []):
        url_rel = entry["url"]
        local_rel = entry["localfile"]

        ensure_lzma_from_local(root, url_rel, local_rel)

        url_file = root / url_rel
        packed_hash, packed_size = sha256_and_size(url_file)

        if entry.get("packedhash") != packed_hash:
            entry["packedhash"] = packed_hash
            updated_fields += 1
        if entry.get("packedsize") != packed_size:
            entry["packedsize"] = packed_size
            updated_fields += 1

        local_file = root / local_rel
        if local_file.exists():
            unpacked_hash, unpacked_size = sha256_and_size(local_file)
        elif url_rel.endswith(".lzma"):
            unpacked_hash, unpacked_size = unpacked_sha256_and_size_from_lzma(url_file)
        else:
            unpacked_hash, unpacked_size = packed_hash, packed_size

        if entry.get("unpackedhash") != unpacked_hash:
            entry["unpackedhash"] = unpacked_hash
            updated_fields += 1
        if entry.get("unpackedsize") != unpacked_size:
            entry["unpackedsize"] = unpacked_size
            updated_fields += 1

    manifest_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data, updated_fields


def main():
    parser = argparse.ArgumentParser(description="Automate OTBaiak Windows release manifests")
    parser.add_argument("--root", default=".", help="Client repo root (default: current dir)")
    parser.add_argument("--generation", help="New generation value for version.json (e.g. otbaiak-v1.1)")
    parser.add_argument("--version", help="New version value for version.json (e.g. 15.11.custom)")
    parser.add_argument("--revision", type=int, help="New revision value for version.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    client_data, client_updates = update_manifest(root, "client.windows.json")
    _, assets_updates = update_manifest(root, "assets.windows.json")

    version_path = root / "version.json"
    if version_path.exists():
        version_data = json.loads(version_path.read_text(encoding="utf-8"))
    else:
        version_data = {
            "version": client_data.get("version", ""),
            "revision": client_data.get("revision", 1),
            "generation": client_data.get("generation", "otbaiak-v1.0"),
            "variant": client_data.get("variant", "otbaiak"),
        }

    if args.generation:
        version_data["generation"] = args.generation
    if args.version:
        version_data["version"] = args.version
    if args.revision is not None:
        version_data["revision"] = args.revision

    version_path.write_text(json.dumps(version_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    exe = root / "OTBaiak.exe"
    if exe.exists():
        exe_hash, _ = sha256_and_size(exe)
        (root / "OTBaiak.exe.sha256").write_text(f"{exe_hash}  OTBaiak.exe\n", encoding="utf-8")

    print("Done")
    print(f"client.windows.json fields updated: {client_updates}")
    print(f"assets.windows.json fields updated: {assets_updates}")
    print(f"version.json: {version_data}")


if __name__ == "__main__":
    main()
