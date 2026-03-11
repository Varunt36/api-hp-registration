-- ============================================================
-- Migration 002: Fix seq auto-increment + allow reference NULL temporarily
-- Run this in Supabase SQL Editor
-- ============================================================

-- 1. Create a sequence for the seq column (BIGSERIAL equivalent)
CREATE SEQUENCE IF NOT EXISTS registrations_seq_seq
  AS BIGINT
  START WITH 3        -- adjust to max(seq)+1 from your data
  INCREMENT BY 1
  NO MINVALUE
  NO MAXVALUE
  CACHE 1;

-- 2. Set the sequence as the default for seq column
ALTER TABLE registrations
  ALTER COLUMN seq SET DEFAULT nextval('registrations_seq_seq');

-- 3. Link the sequence to the column (so it auto-drops with the table)
ALTER SEQUENCE registrations_seq_seq OWNED BY registrations.seq;

-- 4. Allow reference to be NULL temporarily (we set it right after insert)
ALTER TABLE registrations
  ALTER COLUMN reference DROP NOT NULL;

-- 5. Add qr_url column to members if not exists
ALTER TABLE members ADD COLUMN IF NOT EXISTS qr_url TEXT;

-- 6. Verify: check the current max seq to make sure START WITH is correct
SELECT MAX(seq) AS current_max_seq FROM registrations;
