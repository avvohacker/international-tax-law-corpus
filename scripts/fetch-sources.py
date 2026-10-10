"""Fetch every input the pipeline reads, exactly as the register declares.

`provenance/sources.yaml` is the contract: each entry names a URL, the local
`file` it must land in, and the SHA-256 of the exact bytes the extraction was
run on. This script downloads what is missing (or re-verifies what is there)
and fails loudly when a hash does not match, so a runner - CI or human - gets
the same bytes the corpus was built from, or an error instead of a quiet
substitution.

The MLI positions family shares one `url_pattern` with a `{slug}` slot; the
per-file hashes live in the family's `manifest`, whose filenames give the
slugs. Entries with no downloadable file (the `akn-xsd` schema, whose hash is
still pending) are skipped with a reason rather than fetched.

Only the standard library plus PyYAML is used.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "provenance" / "sources.yaml"
SEALED_DIR = ROOT / "sealed"
SEALED_KEY_ENV = "UN_MODEL_2021_KEY"

# Upstream renamed a file without changing its bytes: the register's manifest
# still names mli-position-russian-federation.pdf (hash f1c7e2b6, verified
# 2026-10-10), but the publisher now serves those exact bytes at the
# -instrument-deposit URL. Slugs listed here download from the override URL
# and are hash-verified like everything else, so a changed file still fails.
URL_OVERRIDES = {
    "russian-federation":
        "https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/"
        "beps-mli/beps-mli-position-russian-federation-instrument-deposit.pdf",
}

RETRIES = 3
TIMEOUT = 120


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "international-tax-law-corpus/1.0"})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                with target.open("wb") as handle:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        handle.write(chunk)
            return
        except Exception as error:  # noqa: BLE001 - retried, then reported
            last_error = error
            time.sleep(2 * attempt)
    raise RuntimeError(f"could not download {url}: {last_error}")


def unseal(target: Path, problems: list[str]) -> bool:
    """Decrypt sealed/<name>.enc into place using the env passphrase.

    The UN Model 2021 PDF cannot be fetched by automated clients (the UN
    hosts demand human verification), and its licence forbids committing it.
    The repository therefore carries only AES-256 ciphertext; the passphrase
    lives in the CI secret named by SEALED_KEY_ENV, never in the repo. Without
    the key this reports the file missing instead of guessing.
    """
    sealed = SEALED_DIR / (target.name + ".enc")
    if not sealed.is_file():
        return False
    key = os.environ.get(SEALED_KEY_ENV, "")
    if not key:
        problems.append(f"{target}: sealed copy present but "
                        f"${SEALED_KEY_ENV} is not set")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
         "-in", str(sealed), "-out", str(target),
         "-pass", f"env:{SEALED_KEY_ENV}"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        problems.append(f"{target}: decryption failed: "
                        f"{proc.stderr.strip()}")
        return False
    print(f"unsealed {target}")
    return True


def check(path: Path, declared: str, where: str, problems: list[str]) -> None:
    live = sha256_of(path)
    if live != declared:
        problems.append(f"{where}: hash mismatch for {path} "
                        f"(register {declared}, downloaded {live})")
    else:
        print(f"ok  {path} ({path.stat().st_size} bytes)")


def main() -> int:
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8")) or []
    problems: list[str] = []
    fetched = 0
    for entry in register:
        ident = str(entry.get("id") or "?")
        # Single-file entries: url + file + sha256.
        url = str(entry.get("url") or "")
        relative = str(entry.get("file") or "")
        declared = str(entry.get("sha256") or "")
        if url and relative and declared and declared != "pending":
            path = ROOT / relative
            if not path.is_file() and not unseal(path, problems):
                print(f"get {url}")
                try:
                    download(url, path)
                except RuntimeError as error:
                    problems.append(f"{ident}: {error}")
                    continue
                fetched += 1
            if path.is_file():
                check(path, declared, ident, problems)
            continue
        # Family entries: url_pattern + dir + manifest of per-file hashes.
        pattern = str(entry.get("url_pattern") or "")
        directory = str(entry.get("dir") or "")
        manifest = str(entry.get("manifest") or "")
        if pattern and directory and manifest:
            manifest_path = ROOT / manifest
            if not manifest_path.is_file():
                problems.append(f"{ident}: manifest {manifest} is missing")
                continue
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, _, listed = line.partition("  ")
                listed = listed.strip()
                path = ROOT / listed
                if not path.is_file():
                    name = Path(listed).name
                    prefix, suffix = "mli-position-", ".pdf"
                    if not (name.startswith(prefix) and name.endswith(suffix)):
                        problems.append(f"{ident}: cannot derive a slug "
                                        f"from {listed}")
                        continue
                    slug = name[len(prefix):-len(suffix)]
                    url = URL_OVERRIDES.get(slug, pattern.format(slug=slug))
                    print(f"get {listed}")
                    try:
                        download(url, path)
                    except RuntimeError as error:
                        problems.append(f"{ident}: {error}")
                        continue
                    fetched += 1
                check(path, digest.strip(), ident, problems)
            continue
        print(f"skip {ident}: nothing downloadable declared")
    print(f"fetched {fetched} file(s)")
    if problems:
        print("FAILURES:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
