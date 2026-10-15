# This server as a remote endpoint: what it would take

Written 2026-10-15, while the server was committed in the corpus under `mcp/` and
still spoke stdio only. It is a study, not a plan: it states what exists, what
would have to be built, and what the numbers are, so the decision can be taken
with them rather than around them.

## The transport is not the hard part

The pinned SDK (`mcp==2.3.0`) already offers all three transports:

```python
MCPServer.run(self, transport: Literal["stdio", "sse", "streamable-http"] = "stdio", **kwargs)
```

This server calls `mcp.run(transport="stdio")` in `main()`, and nothing about the
tools, the payloads or the refusals depends on the transport: the decorators
register against the same object. `MCPServer(...)` also takes `auth_server_provider`
(an OAuth provider), `middleware` and `lifespan`, so authentication and
per-request hooks are constructor arguments rather than a rewrite.

Honest scope of that sentence: it is a parameter *plus* configuration (host, port,
path) *plus* whatever the deployment needs — TLS, a supervisor, a health check.
None of that is puzzle-solving; all of it is work.

## The data is the hard part

The process reads files. `itl_mcp.roots.load_roots()` validates **two directories**
(`ITL_CORPUS_ROOT`, `ITL_LIBRARY_ROOT`) at startup, and the readers open paths
inside them. A container has no such checkout unless it is given one.

Measured on this checkout, tracing every file the server opens:

| the questions asked | files touched | bytes read |
| --- | --- | --- |
| every question the drift control records, plus a refusal and a page | **134** | **14.2 MB** |
| the two verdicts plus one refusal, only | **24** | **441.5 KB** |

The difference is `sources`, which verifies every artefact the registers declare:
it walks the whole corpus — the two span ledgers alone are 8.4 MB, and every one
of the 103 MLI position documents is opened. The two verdicts by themselves read
seven artefacts, about 420 KB in total:

| artefact | size |
| --- | --- |
| `corpora/mli/positions/united-kingdom.json` | 117.9 KB |
| `library/treaties/uk-us-2001/treaty.json` | 103.8 KB |
| `library/treaties/no-uk-2013/treaty.json` | 75.4 KB |
| `corpora/mli/positions/norway.json` | 45.6 KB |
| `corpora/mli/signatories-and-parties.json` | 37.5 KB |
| `corpora/mli/mapping.json` | 15.1 KB |
| `provenance/sources.yaml` + `provenance/mli-positions.sha256` | 22.6 KB |

So there are two ways to give a remote process its data, and they differ in who
pays for keeping it current:

* **Ship the artefacts with the deploy.** The footprint above is the bill: about
  14 MB if the verification tool is to answer as it does here, 22.6 MB for the
  whole corpus. Every corpus push then needs a rebuild and a redeploy, because a
  container built yesterday holds yesterday's bytes — while the corpus' own
  contract says the bytes are reproducible, so a rebuild is deterministic rather
  than risky.
* **Fetch at request time.** Always current, and the verification survives
  fetching: the server already recomputes each declared hash against the bytes it
  reads, so a fetched deployment proves the same things a checked-out one does.
  What it pays instead is bytes per cold call — 14 MB if `sources` is asked, 420 KB
  for the verdicts — which is why this option is inseparable from a cache, and a
  cache is a new thing to keep correct (a stale cache is a wrong answer with a
  fresh timestamp).

Reading is path-based today, so either way a **reading layer** has to exist: the
same readers, opened from a bundle or a cache instead of from a directory. That
is the real work, and it is a feature with its own tests, not a flag.

## What else the endpoint forces

* **Authentication.** The data are public and the answers are not secret, but an
  open endpoint is free CPU for anyone: a token, or a rate limit, or both. The SDK
  has the hook; the policy is ours.
* **Cold-start cost.** Every request that re-verifies reads 14 MB; a stateless
  endpoint would do that per call. Either `sources` is cached per deployment (with
  the corpus commit it verified), or the endpoint is warm and long-lived.
* **Where it runs.** A Python process needs a host that runs Python containers.
  The Sites target available to this project is a Workers runtime — JavaScript or
  WebAssembly, no Python — so this server cannot be deployed there as it stands;
  a Workers/TypeScript port would be a second implementation of the same answers,
  and the drift control that holds one implementation would have to hold two.

## What it would cost in this repository

1. a second entrypoint (`--transport streamable-http`, host/port from arguments),
   with `main()` unchanged for stdio;
2. a control that asks both transports the same questions and requires the same
   answers — the pattern of `tests/test_the_folder_travels.py`, which already
   compares two processes rather than trusting one;
3. the reading layer, and its tests, for whichever data decision is taken;
4. a deploy job, which needs a host credential — and a credential is a promise
   that something outside this repository is kept in step.

## The decision, stated as a question

Not "can it be done" — it can — but: **who reads this, and from where?** Today the
answer is a person with the two checkouts and a host that can spawn a process,
which is exactly how the corpus and the library are used anyway. A remote endpoint
buys reach: an AI client with no filesystem at all. It costs a second place where
the data live, and therefore a second thing that can be stale.
