# Python dependency locking

The supported runtime is 64-bit CPython 3.12.10. `backend/requirements.txt`
contains exact direct pins. `backend/requirements.lock` is the complete,
unhashed environment captured from the working Windows prototype on 2026-08-31.
It makes the current bootstrap deterministic by version, but it is a candidate
lock rather than the final supply-chain lock.

Run the static, offline contract check from the package root:

    python deploy/locks/audit_lock.py

Before public release, generate locks independently on clean Windows and Linux
hosts using the scripts in this directory. They require an already installed,
reviewed `pip-tools`; the scripts never install tooling implicitly. Generated
files use hashes and must be retained as
`requirements.windows-py312.lock` and `requirements.linux-py312.lock`.

Then create a fresh virtual environment on each platform, install its lock with
`pip install --require-hashes -r <platform-lock>`, run `pip check`, the complete
test suite, migrations, and the ingestion-to-output smoke test. A lock is not
accepted merely because resolution succeeded. Record Python, pip, OS/architecture,
lock SHA-256, commands, and results in the clean-room evidence.

The Docker base is pinned to the Python patch tag but not yet to an immutable
image digest. Resolve and record the multi-architecture digest during the Linux
clean-room/release process; do not copy a digest from an unverified source.

Optional spaCy and sentence-transformer model assets are not downloaded by the
image. Each asset needs a version, checksum, licence and explicit installation
step. Until supplied, its dependent semantic capability must report unavailable.
