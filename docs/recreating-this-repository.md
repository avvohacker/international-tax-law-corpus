# Recreating this repository

A repository is its files **plus** its settings, and only the files come back
when you push. Everything below was learned by deleting and recreating this
repository on 2026-10-11, and each item is written as the failure it produces,
because that is the form in which it arrives: a red run that looks like a
problem with the corpus and is a problem with the settings.

## 1. The repository secret `UN_MODEL_2021_KEY`

The 2021 UN Model PDF is never committed, and the UN host answers `403` to
automated clients, so a runner cannot fetch it. The repository therefore carries
the ciphertext `sealed/un-model-2021.pdf.enc` and `scripts/fetch-sources.py`
decrypts it into place with this secret.

Without the secret the `corpus-drift` fetch step fails **before anything is
read**, so the run is red for a reason no artefact explains.

Two failures, and the message tells them apart:

* `sealed copy present but $UN_MODEL_2021_KEY is not set` — the secret is
  absent **or empty**. `gh secret set` accepts an empty value without
  complaining, so

      printf '%s' "$UN_MODEL_2021_KEY" | gh secret set UN_MODEL_2021_KEY ...

  run in a shell where that variable was never defined sets an *empty* secret
  and prints a success. To tell an empty secret apart from a stale re-run,
  dispatch a **new** run (`gh workflow run corpus-drift.yml`): a re-run that
  fails the same way is not the cache, it is the value.

* `decryption failed: ...` — the secret is set and is not the passphrase this
  ciphertext was sealed with.

### Regenerating the sealed copy

The ciphertext is **not** hash-pinned anywhere; only the plaintext is, in
`provenance/sources.yaml` under `un-model-2021`. So a new passphrase is
legitimate exactly as long as the plaintext it yields is byte-identical to the
registered one — and that is checkable before anything is published:

    # 1. seal, with the same command line the workflow uses, in reverse
    openssl enc -aes-256-cbc -pbkdf2 \
      -in sources/un-model-2021.pdf -out sealed/un-model-2021.pdf.enc \
      -pass env:UN_MODEL_2021_KEY

    # 2. prove it opens with the exact decrypt command fetch-sources.py runs
    openssl enc -d -aes-256-cbc -pbkdf2 \
      -in sealed/un-model-2021.pdf.enc -out /tmp/check.pdf \
      -pass env:UN_MODEL_2021_KEY

    # 3. and that the bytes are the registered ones
    shasum -a 256 /tmp/check.pdf     # must equal provenance/sources.yaml's pin

The passphrase lives in the repository secret and nowhere else: not in the
repository, not in this file, not in the workflow. Keep the only copy of it
somewhere you will still have it tomorrow — a lost passphrase is recoverable
only by re-fetching the PDF from the UN in a browser and sealing it again.

## 2. The sibling checkout needs the library readable

`mcp-drift` checks the library out beside this repository, because neither this
repository nor the server committed inside it carries the bilateral treaties the
server answers from. The `GITHUB_TOKEN` is scoped to the repository running the
workflow, so it reads a **public** sibling and cannot read a private one: the
checkout fails with
`Not Found — https://docs.github.com/rest/repos/repos#get-a-repository`. The
library is public, so that checkout succeeds; a private one would make the
server's runs red for a reason no artefact explains, and a workflow that needs a
private sibling needs a token with access to it, which the default token is not.

The corpus' `discipline` job used to check the library out as well, and does not
any more: that job holds the two checkouts this repository holds — itself and
`mcp/` — and the library's half of the shared rules is read by the same script in
the library's own `discipline-drift` workflow, over this corpus, where
`revendor-discipline` opens the repair. A job that reports a copy no reader of the
run can write is a red with no action behind it; the halves still cannot part
company quietly, because they are compared in the repository that can act on the
answer. `tests/test_the_control_holds_what_it_can_repair.py` holds this side of the
split: the job checks out no other repository, hands the control no `--library`,
and the command it declares — run by the test — names the layer it was not handed
and where that half is read. Those two workflow names are the library's to change,
and this paragraph and the comment on the `discipline` job of `corpus-drift.yml`
are what move with them.

The server itself used to be a third checkout here and is not one any more: it is
committed in this repository, under `mcp/`, so nothing about it depends on
another repository being readable.

## 3. What else git does not carry

* **Description and topics.** The description is what a search hit shows, and
  the topics are how the repository is found at all. Both are set on the
  repository, not in it.
* **Actions enabled**, and the workflow files present. A workflow that was
  disabled stays disabled across nothing: it is a repository setting.
* **Visibility.** A recreated repository is private until you say otherwise,
  and item 2 above is what that costs.

## The layers, and what each needs to be green

| repository | what the runner must be able to reach | the failure when it cannot |
| --- | --- | --- |
| corpus | the secret `UN_MODEL_2021_KEY`; the UN host, for every source but `un-model-2021`; the library, read-only, for the two controls of item 2 | fetch step fails, or `Not Found` on the library checkout |
| library | the publisher hosts for its treaties' PDFs | fetch step fails, nothing is read |
| mcp (in this repository, under `mcp/`) | the library, read-only — the corpus it reads is the checkout it is committed in | `Not Found` on the library checkout |

## What this page is not

It is not a backup. The sources are not in the repository and never will be:
the hash is the contract, the file is not. What stands between this repository
and the sources it reads is the publisher, the passphrase above, and these
notes.

The date of this page's own first version is 2026-10-11, the day the repository
was recreated it describes. It is a record of what went wrong, kept where the
next person to press *delete* will read it.
