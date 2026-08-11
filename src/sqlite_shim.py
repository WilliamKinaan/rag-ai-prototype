"""Swap in `pysqlite3-binary` for the stdlib `sqlite3` module, if available.

Chroma requires sqlite3 >= 3.35.0. Some Linux distros ship an older system
sqlite3 than that (notably RHEL-family — Oracle Linux 9, e.g. — and older
Debian), which makes `import chromadb` fail with:

    RuntimeError: Your system has an unsupported version of sqlite3.

`pysqlite3-binary` bundles a modern sqlite3 build. When it's installed, this
module points Python's `sqlite3` name at it *before* anything else imports
sqlite3 — the swap only affects imports that happen after this runs, so
every entrypoint that touches Chroma must `import sqlite_shim` before
`import chromadb` (see ingest.py, query.py, test.py, webapp/app.py).

Harmless no-op if pysqlite3-binary isn't installed — e.g. on macOS, where
the system sqlite3 is already new enough that this package is never
installed (see requirements.txt: it's a Linux-only conditional dependency).
"""
try:
    import pysqlite3  # type: ignore

    import sys

    sys.modules["sqlite3"] = pysqlite3
    print(f"[sqlite_shim] using pysqlite3 {pysqlite3.sqlite_version} in place of the system sqlite3")
except ImportError:
    pass
