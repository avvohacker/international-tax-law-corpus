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

Two things about a runner with more than one job (`ITL_SOURCE_CACHE`):

* the bytes fetched over the network are kept in that directory - by their
  name, after their hash was verified - so the next job can reuse them instead
  of downloading 116 files (135.7 MB, measured with `scripts/read-audit.py`)
  again. A cached file that does not hash to the register is ignored, so a
  stale entry costs a download and never a wrong corpus;
* a source that has a sealed copy under `sealed/` is never cached, whatever
  route its bytes arrived by. `sealed/un-model-2021.pdf.enc` is ciphertext the
  repository may carry and the plaintext is what the register's passphrase
  protects; a cache is restorable from a pull request, so the decrypted file
  must not be able to end up in one. `keep()` refuses those names by looking at
  `sealed/`, not at how the file was obtained.

Only the standard library plus PyYAML is used.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTER_NAME = Path("provenance") / "sources.yaml"
SEALED_NAME = Path("sealed")
SEALED_KEY_ENV = "UN_MODEL_2021_KEY"
CACHE_ENV = "ITL_SOURCE_CACHE"

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


def cache_dir() -> Path | None:
    """The shared cache of fetched bytes, when the runner names one."""
    raw = os.environ.get(CACHE_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def sealed_names(sealed_dir: Path) -> set[str]:
    """The files the repository carries sealed, by their local name."""
    return {sealed.name[:-len(".enc")] for sealed in sealed_dir.glob("*.enc")}


def from_cache(target: Path, declared: str, cache: Path | None) -> bool:
    """Reuse bytes an earlier job fetched and verified, if they are there.

    A cache hit is not a promise: the hash is checked here, so an entry that is
    stale, truncated or half-written costs the download it was meant to save.
    """
    if cache is None:
        return False
    candidate = cache / target.name
    if not candidate.is_file() or sha256_of(candidate) != declared:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, target)
    return True


def keep(target: Path, cache: Path | None, sealed: set[str]) -> None:
    """Save a file that arrived over the network, so the next job need not.

    Two refusals, both deliberate: nothing is cached when the runner named no
    cache, and nothing with a sealed copy is cached at all - the plaintext of a
    sealed source is the one thing a cache restorable from a pull request must
    not be able to hold.
    """
    if cache is None or target.name in sealed:
        return
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, cache / target.name)


def unseal(target: Path, problems: list[str], sealed_dir: Path) -> bool:
    """Decrypt sealed/<name>.enc into place using the env passphrase.

    The UN Model 2021 PDF cannot be fetched by automated clients (the UN
    hosts demand human verification), and this repository commits no publisher's
    PDF whatever its holder permits - here the ciphertext is how the source
    travels, and the register records the UN's own terms next to its hash.
    The repository therefore carries only AES-256 ciphertext; the passphrase
    lives in the CI secret named by SEALED_KEY_ENV, never in the repo. Without
    the key this reports the file missing instead of guessing.
    """
    sealed = sealed_dir / (target.name + ".enc")
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


def place(ident: str, target: Path, url: str, declared: str, problems: list[str],
          cache: Path | None, sealed: set[str]) -> str | None:
    """Put the declared bytes at `target`: the cache first, the network last.

    Returns how they arrived - `cache` or `download` - or None when neither
    route worked, with the reason appended to `problems`.
    """
    if from_cache(target, declared, cache):
        print(f"cache {target}")
        return "cache"
    print(f"get {url}")
    try:
        download(url, target)
    except RuntimeError as error:
        problems.append(f"{ident}: {error}")
        return None
    keep(target, cache, sealed)
    return "download"


def main(root: Path | None = None) -> int:
    root = Path(root) if root else ROOT
    register = yaml.safe_load((root / REGISTER_NAME).read_text(encoding="utf-8")) or []
    sealed_dir = root / SEALED_NAME
    cache = cache_dir()
    sealed = sealed_names(sealed_dir)
    problems: list[str] = []
    placed = {"download": 0, "cache": 0}
    for entry in register:
        ident = str(entry.get("id") or "?")
        # Single-file entries: url + file + sha256.
        url = str(entry.get("url") or "")
        relative = str(entry.get("file") or "")
        declared = str(entry.get("sha256") or "")
        if url and relative and declared and declared != "pending":
            path = root / relative
            if not path.is_file() and not unseal(path, problems, sealed_dir):
                arrival = place(ident, path, url, declared, problems, cache, sealed)
                if arrival is None:
                    continue
                placed[arrival] += 1
            if path.is_file():
                check(path, declared, ident, problems)
            continue
        # Family entries: url_pattern + dir + manifest of per-file hashes.
        pattern = str(entry.get("url_pattern") or "")
        directory = str(entry.get("dir") or "")
        manifest = str(entry.get("manifest") or "")
        if pattern and directory and manifest:
            manifest_path = root / manifest
            if not manifest_path.is_file():
                problems.append(f"{ident}: manifest {manifest} is missing")
                continue
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, _, listed = line.partition("  ")
                listed = listed.strip()
                path = root / listed
                if not path.is_file():
                    name = Path(listed).name
                    prefix, suffix = "mli-position-", ".pdf"
                    if not (name.startswith(prefix) and name.endswith(suffix)):
                        problems.append(f"{ident}: cannot derive a slug "
                                        f"from {listed}")
                        continue
                    slug = name[len(prefix):-len(suffix)]
                    url = URL_OVERRIDES.get(slug, pattern.format(slug=slug))
                    arrival = place(ident, path, url, digest.strip(), problems,
                                    cache, sealed)
                    if arrival is None:
                        continue
                    placed[arrival] += 1
                check(path, digest.strip(), ident, problems)
            continue
        print(f"skip {ident}: nothing downloadable declared")
    print(f"placed {placed['download'] + placed['cache']} file(s): "
          f"{placed['download']} downloaded, {placed['cache']} from the cache")
    if problems:
        print("FAILURES:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
