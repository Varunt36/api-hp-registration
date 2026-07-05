-- ============================================================
-- Form Reminder Sends — tracks the travel & accommodation form outreach
-- (email + WhatsApp), so a later run can reach only those who did NOT
-- receive it yet, and so failures keep their exception detail for retry.
--
-- Run this in the Supabase SQL Editor.
-- ============================================================

CREATE TABLE IF NOT EXISTS form_reminder_sends (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id       UUID        NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  email           TEXT        NOT NULL,          -- recipient at time of send
  full_name       TEXT,                          -- recipient name at time of send
  channel         TEXT        NOT NULL CHECK (channel IN ('email', 'whatsapp')),
  status          TEXT        NOT NULL CHECK (status IN ('sent', 'failed')),
  error_detail    TEXT,                          -- exception message when status = 'failed'
  form_url        TEXT,                          -- which form link was sent
  attempts        INT         NOT NULL DEFAULT 1,-- incremented on each retry
  sent_at         TIMESTAMPTZ,                   -- set only when status = 'sent'
  last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- One current row per recipient per channel. Serves two purposes:
  --   1. the sender UPSERTs on this: ON CONFLICT (member_id, channel) DO UPDATE
  --   2. its btree also indexes the member_id FK (leading column), so JOINs and
  --      ON DELETE CASCADE are fast — no separate member_id index is needed.
  UNIQUE (member_id, channel)
);

-- Fast "who failed / who to retry" lookups. Kept as a plain composite; if this
-- table ever grows across many campaigns, a partial index on failures
-- (WHERE status = 'failed') would be smaller and faster for the retry query.
CREATE INDEX IF NOT EXISTS idx_frs_channel_status
  ON form_reminder_sends (channel, status);

-- Backend-only table: the sender uses the service_role key (which bypasses
-- RLS). Enable RLS with NO policies so the Data API (anon / authenticated
-- roles) cannot read or write this outreach log.
ALTER TABLE form_reminder_sends ENABLE ROW LEVEL SECURITY;
