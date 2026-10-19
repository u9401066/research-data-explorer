# Windows persistence

Windows cannot open directories with the POSIX `os.open(..., O_RDONLY)` API used for directory `fsync`. On Windows, sealed plan and execution receipts now retain their file flush and atomic replacement, but omit that unsupported directory operation. Existing copied artifact files use `r+b` when flushing so Windows receives a writable handle without truncation. POSIX directory synchronization and error propagation remain mandatory.

This fixes the applicable persistence defects reported against RDE 0.5.4 and adapts them to the 0.6.x implementation. It does not change plan approval, source hashes, immutable replay or analytical methods. The source catalog is regenerated from current files rather than copied from the older recommendation.

`tests/test_windows_durability.py` checks Unicode sealed writes, identical replay, refusal of changed immutable content, exact byte preservation, writable-handle flush and propagation/closure of POSIX fsync failures. The `windows-receipts` CI job runs these tests on native Windows; Linux simulation alone does not establish Windows execution.

Omitting directory fsync is a platform limitation, not equivalent protection against power loss. NTFS journaling alone does not prove the same durability semantics. Native file I/O errors still propagate. Old receipts are not rewritten or retrospectively revalidated.
