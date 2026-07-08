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
  amount           NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),  -- >= 0 so 100%-coupon (€0) payments are allowed
  currency         TEXT           NOT NULL DEFAULT 'EUR',
  payment_method   TEXT           CHECK (payment_method IN ('stripe')),
  transaction_id   TEXT           UNIQUE,     -- from Stripe webhook
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
  country_name  TEXT,
  dial_code     TEXT,
  flag          TEXT,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed with current production quotas (keep in sync with frontend dropdown in
-- hp-landing-page/src/data/data.ts)
INSERT INTO country_quotas (country_code, max_members, country_name, dial_code, flag) VALUES
  ('AE',   5, 'United Arab Emirates', '+971', '🇦🇪'),
  ('AU',   5, 'Australia',            '+61',  '🇦🇺'),
  ('CA',  50, 'Canada',               '+1',   '🇨🇦'),
  ('DE', 150, 'Germany',              '+49',  '🇩🇪'),
  ('GB', 100, 'United Kingdom',       '+44',  '🇬🇧'),
  ('IN',  30, 'India',                '+91',  '🇮🇳'),
  ('NZ',   5, 'New Zealand',          '+64',  '🇳🇿'),
  ('PL',  10, 'Poland',               '+48',  '🇵🇱'),
  ('US', 100, 'United States',        '+1',   '🇺🇸');
