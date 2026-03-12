-- Add emails_sent flag to payments table for tracking email delivery.
-- Allows admin to identify and retry failed email deliveries.
-- NULL = not yet attempted, TRUE = sent, FALSE = failed
ALTER TABLE payments ADD COLUMN emails_sent BOOLEAN DEFAULT NULL;
