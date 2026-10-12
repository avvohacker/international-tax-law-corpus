"""The fetch's cache, and the one thing it must never hold.

`scripts/fetch-sources.py` can reuse the bytes an earlier CI job downloaded
(`ITL_SOURCE_CACHE`), which is what stops three jobs from each fetching 116
files and 135.7 MB. What a cache may hold is the whole question: the public
third-party PDFs, hash-verified, and never the plaintext of a sealed source -
a cache entry is restorable from a pull request, and the register's passphrase
is deliberately not given to one. That refusal lives in the fetcher and is
tested here, because it is not visible in any artefact: a cache that quietly
held the Model 2021 PDF would leave every other test green.
"""

import hashlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = b"the registered bytes\n"


def _fetcher():
    """The fetcher, loaded by path: its name is not an importable module."""
    spec = importlib.util.spec_from_file_location(
        "fetch_sources", ROOT / "scripts" / "fetch-sources.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_sources"] = module
    spec.loader.exec_module(module)
    return module


def _checkout(tmp_path: Path, *, sealed: bool = False, name: str = "sample.bin"):
    """A checkout with one registered source, and the file it is published at.

    The URL points at a real file the test owns, so a "download" is a copy and
    the test can delete it to prove that the network was not the route taken.
    """
    published = tmp_path / "published" / name
    published.parent.mkdir(parents=True)
    published.write_bytes(PAYLOAD)
    root = tmp_path / "checkout"
    (root / "provenance").mkdir(parents=True)
    (root / "provenance" / "sources.yaml").write_text(
        f"- id: sample\n"
        f"  url: {published.as_uri()}\n"
        f"  file: sources/{name}\n"
        f"  sha256: {hashlib.sha256(PAYLOAD).hexdigest()}\n",
        encoding="utf-8")
    if sealed:
        (root / "sealed").mkdir()
        (root / "sealed" / (name + ".enc")).write_bytes(b"ciphertext")
    return root, published


def test_a_cached_file_saves_the_download(tmp_path, monkeypatch):
    root, published = _checkout(tmp_path)
    published.unlink()               # a download would now fail, by design
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "sample.bin").write_bytes(PAYLOAD)
    monkeypatch.setenv("ITL_SOURCE_CACHE", str(cache))

    fetcher = _fetcher()
    assert fetcher.main(root) == 0
    assert (root / "sources" / "sample.bin").read_bytes() == PAYLOAD


def test_a_stale_cache_entry_is_ignored(tmp_path, monkeypatch):
    """A cache hit is not a promise: the hash decides, every time."""
    root, published = _checkout(tmp_path)
    published.unlink()
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "sample.bin").write_bytes(b"something else entirely\n")
    monkeypatch.setenv("ITL_SOURCE_CACHE", str(cache))

    fetcher = _fetcher()
    assert fetcher.main(root) == 1, "a stale entry has to be refused, loudly"
    assert not (root / "sources" / "sample.bin").exists()


def test_a_fetched_source_is_kept_for_the_next_job(tmp_path, monkeypatch):
    root, _ = _checkout(tmp_path)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ITL_SOURCE_CACHE", str(cache))

    fetcher = _fetcher()
    assert fetcher.main(root) == 0
    assert (cache / "sample.bin").read_bytes() == PAYLOAD


def test_the_plaintext_of_a_sealed_source_never_reaches_the_cache(tmp_path,
                                                                 monkeypatch):
    root, _ = _checkout(tmp_path, sealed=True)
    cache = tmp_path / "cache"
    monkeypatch.setenv("ITL_SOURCE_CACHE", str(cache))
    monkeypatch.delenv("UN_MODEL_2021_KEY", raising=False)

    fetcher = _fetcher()
    # No passphrase is set, so the sealed copy cannot be opened: the script
    # reports that instead of guessing, and the bytes it does get come over the
    # network - which is exactly the route that must still not fill the cache.
    assert fetcher.main(root) == 1
    assert (root / "sources" / "sample.bin").is_file()
    assert not (cache / "sample.bin").exists(), (
        "a source with a sealed copy must never be cached: a cache entry is "
        "restorable from a pull request, and the passphrase is not")
