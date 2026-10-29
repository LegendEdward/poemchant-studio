# Security and privacy

The application listens only on `127.0.0.1` and chooses an available port. Editing requests require a per-session token and matching origin. No corpus download, remote inference, telemetry or automatic update connection is used at runtime.

Projects are untrusted JSON: original text, ordering, signatures, finite numeric ranges and current-model provenance are checked. Model imports accept bounded ZIP files, reject unsafe paths and symlinks, verify a known implementation and file hashes, and never execute code supplied in the archive. CSV formula-like annotation values are protected; JSON retains their original text.

Do not commit your local `projects/`, `model_packs/`, credentials or private recordings. If reporting a defect, provide a minimal non-private input and remove private paths. Do not post credentials in public issues. The repository has no private security mailbox; use GitHub's private vulnerability reporting if enabled by its owner.
