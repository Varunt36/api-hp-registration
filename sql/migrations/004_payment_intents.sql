-- 004_payment_intents.sql
-- Server-side store for the registration payload between /create-payment and webhook completion.
-- Replaces the Stripe-metadata-flattening encoder; carries a UUID through the provider.

CREATE TABLE payment_intents (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  reference       TEXT          NOT NULL REFERENCES registrations(reference),
  provider        TEXT          NOT NULL CHECK (provider IN ('stripe', 'paypal')),
  payload         JSONB         NOT NULL,
  amount          NUMERIC(10,2) NOT NULL CHECK (amount > 0),
  currency        TEXT          NOT NULL DEFAULT 'EUR',
  status          TEXT          NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'consumed', 'expired')),
  expires_at      TIMESTAMPTZ   NOT NULL,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_payment_intents_reference  ON payment_intents(reference);
CREATE INDEX idx_payment_intents_expires_at ON payment_intents(expires_at) WHERE status = 'pending';
