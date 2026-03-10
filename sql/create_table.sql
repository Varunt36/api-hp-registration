-- ============================================================
-- YDS Germany 2026 — Supabase Schema
-- Run this in Supabase SQL Editor
-- ============================================================


-- ── 1. REGISTRATIONS ────────────────────────────────────────
CREATE TABLE registrations (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  seq           BIGSERIAL   UNIQUE NOT NULL,
  reference     TEXT        UNIQUE,           -- e.g. HP-2026-00042 (set by FastAPI)
  country       TEXT        NOT NULL,
  karyakarta    TEXT        NOT NULL,
  member_count  INT         NOT NULL CHECK (member_count >= 1),
  terms_accepted BOOLEAN    NOT NULL DEFAULT false,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. MEMBERS ──────────────────────────────────────────────
CREATE TABLE members (
  id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id  UUID        NOT NULL REFERENCES registrations(id) ON DELETE CASCADE,
  ticket_number    TEXT        UNIQUE,        -- e.g. HP-2026-00042-M1 (set by FastAPI)
  first_name       TEXT        NOT NULL,
  middle_name      TEXT,
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


-- ── 3. PAYMENTS ─────────────────────────────────────────────
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


-- ── 5. COUNTRY QUOTA ENFORCEMENT ────────────────────────────
-- Trigger that runs BEFORE every registration insert.
-- Raises an error if the new group would exceed the country's member quota.
CREATE OR REPLACE FUNCTION check_country_quota()
RETURNS TRIGGER AS $$
DECLARE
  max_allowed   INT;
  current_count INT;
BEGIN
  -- Get the quota for this country (NULL if no quota set = unlimited)
  SELECT max_members INTO max_allowed
  FROM country_quotas
  WHERE country_code = NEW.country;

  -- No quota row means no limit for this country
  IF max_allowed IS NULL THEN
    RETURN NEW;
  END IF;

  -- Count members already paid from this country
  SELECT COALESCE(SUM(r.member_count), 0) INTO current_count
  FROM registrations r
  JOIN payments p ON p.registration_id = r.id
  WHERE r.country = NEW.country
    AND p.status = 'paid';

  -- Reject if adding this group would exceed the limit
  IF current_count + NEW.member_count > max_allowed THEN
    RAISE EXCEPTION
      'Registration limit reached for country %. Only % spots remain.',
      NEW.country,
      max_allowed - current_count;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_country_quota
  BEFORE INSERT ON registrations
  FOR EACH ROW
  EXECUTE FUNCTION check_country_quota();


-- ── 4. COUNTRY QUOTAS ───────────────────────────────────────
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
