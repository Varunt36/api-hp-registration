-- 005_payments_provider_columns.sql
-- Audit/ops cross-reference back to the provider's order id (PayPal order id, Stripe session id).

ALTER TABLE payments ADD COLUMN provider_order_id TEXT;
CREATE INDEX idx_payments_provider_order_id ON payments(provider_order_id);
