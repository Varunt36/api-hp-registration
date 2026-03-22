-- ============================================================
-- YDS Germany 2026 — Supabase Schema
-- Run this in Supabase SQL Editor
-- ============================================================


-- ── 1. SEQUENCE FOR REGISTRATIONS ─────────────────────────────
CREATE SEQUENCE IF NOT EXISTS registrations_seq_seq
  AS BIGINT
  START WITH 1
  INCREMENT BY 1
  NO MINVALUE
  NO MAXVALUE
  CACHE 1;

-- ── 2. REGISTRATIONS ────────────────────────────────────────
CREATE TABLE registrations (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  seq           BIGINT      UNIQUE NOT NULL DEFAULT nextval('registrations_seq_seq'),
  reference     TEXT        UNIQUE,           -- e.g. HP-2026-00042 (set by FastAPI)
  country       TEXT        NOT NULL,
  karyakarta    TEXT        NOT NULL,
  member_count  INT         NOT NULL CHECK (member_count >= 1),
  terms_accepted BOOLEAN    NOT NULL DEFAULT false,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Link the sequence to the column (auto-drops with the table)
ALTER SEQUENCE registrations_seq_seq OWNED BY registrations.seq;

-- ── 3. MEMBERS ──────────────────────────────────────────────
CREATE TABLE members (
  id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id  UUID        NOT NULL REFERENCES registrations(id) ON DELETE CASCADE,
  ticket_number    TEXT        UNIQUE,        -- e.g. HP-2026-00042-M1 (set by FastAPI)
  first_name       TEXT        NOT NULL,
  last_name        TEXT        NOT NULL,
  gender           TEXT        NOT NULL CHECK (gender IN ('male', 'female')),
  dob              DATE        NOT NULL,
  email            TEXT        NOT NULL,
  phone            TEXT,
  qr_url           TEXT,
  checked_in       BOOLEAN     NOT NULL DEFAULT false,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast lookup by registration
CREATE INDEX idx_members_registration_id ON members(registration_id);


-- ── 4. PAYMENTS ─────────────────────────────────────────────
CREATE TABLE payments (
  id               UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id  UUID           UNIQUE NOT NULL REFERENCES registrations(id) ON DELETE CASCADE,
  status           TEXT           NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending', 'paid', 'failed')),
  amount           NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
  currency         TEXT           NOT NULL DEFAULT 'EUR',
  payment_method   TEXT           CHECK (payment_method IN ('stripe', 'paypal')),
  transaction_id   TEXT           UNIQUE,     -- from Stripe / PayPal webhook
  paid_at          TIMESTAMPTZ,               -- set when status becomes 'paid'
  created_at       TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Index for fast status lookups
CREATE INDEX idx_payments_status ON payments(status);


-- ── 5. COUNTRY QUOTAS ───────────────────────────────────────
-- Must be created BEFORE the trigger that references it
CREATE TABLE country_quotas (
  id            UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
  country_code  TEXT  UNIQUE NOT NULL,        -- e.g. 'DE', 'US', 'IN'
  max_members   INT   NOT NULL CHECK (max_members > 0),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed with initial quotas (update numbers as needed)
INSERT INTO country_quotas (country_code, max_members) VALUES
  ('DE', 100),
  ('AT', 50),
  ('CH', 50),
  ('GB', 30),
  ('US', 20),
  ('IN', 30),
  ('NZ', 20);
