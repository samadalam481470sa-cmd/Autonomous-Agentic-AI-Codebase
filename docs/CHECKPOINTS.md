# Local edit checkpoints and restoration

Part 7.4 checkpoint milestone implemented for approved source edits.

- Storage: SQLite `file_checkpoints` table in the existing local `DB_PATH` database.
- Each checkpoint records project, path, original UTF-8 content, whether the original existed, the applied content hash, applied existence and timestamp.
- Both single-file Studio saves and approved multi-file batches record snapshots before applying file changes.
- To inspect recent checkpoints: authenticated `POST /api/studio/checkpoints` with `{"project":"demo","path":"main.py"}`.
- To restore: authenticated `POST /api/studio/restore` with the same project/path, a listed `checkpoint_id`, the current `expected_sha256`, and `X-Confirm-Change: approve`.
- The server verifies **both** that the current file matches the version produced by the checkpoint and that the caller has its current checksum. Restore itself records another checkpoint (undo).
- Missing-original files are deleted on restore, never replaced with an empty placeholder.
- Writes use sibling temporary files and atomic `os.replace` for an individual file. Updates inside a process use a shared lock.
- Files with symlinks in their path or internal `.agent` / `.git` components are excluded.

## Known limitations

This is not the blueprint's full agent execution checkpoint system, nor is it an external backup. It covers human-approved Studio file writes and batch applies. SQLite snapshots are stored alongside the project on the same machine, with no encrypted-at-rest guarantee. An interrupted batch apply may leave snapshots whose hash no longer matches current files; those cannot be restored without new review. A power loss, external editor, or multiple Python workers can still cause races; database and file operations do not form a single atomic transaction across the filesystem. Full worktree restore, durable job checkpoints, crash-recovery journaling and multi-process synchronization remain future work.
