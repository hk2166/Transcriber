# Storage schema

Plain SQLite, no ORM. Migrations are numbered `NNNN_name.sql` files in
`migrations/`, applied in order by `db.connect()` and recorded in
`schema_migrations` (each runs once). To change the schema, **add a new
migration file** — never edit an applied one.

Database location (app): `~/Library/Application Support/MeetingMind/meetings.db`.

## Tables (0001_initial)

- **meetings** — one row per recording session.
  `id, title, source (mic|system|both), status (recording|processing|ready),
  wav_path, started_at, ended_at, created_at`.
- **transcript_segments** — the transcript. FK `meeting_id` (cascade delete),
  optional `speaker_id`. `text, start_ms, end_ms, language, confidence`.
  Indexed by `(meeting_id, start_ms)`.
- **speakers** — created now, populated by diarization (Day 8).
  `meeting_id, label, name (user override), color`.
- **summaries** — created now, populated by the LLM (Day 9). One per meeting.
  `summary` + JSON arrays `key_points, action_items, decisions, open_questions`.

## Lifecycle

session start → `create_meeting` (status `recording`) · each transcript →
`insert_segment` · session stop → `end_meeting` (status `ready`).

> Packaging note (Day 7): the `migrations/*.sql` files must be bundled with the
> PyInstaller sidecar — they are read from disk at runtime, not imported.
