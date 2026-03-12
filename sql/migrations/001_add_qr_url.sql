-- ============================================================
-- Migration 001: Add qr_url column to members table
-- Run this if the members table already exists without qr_url
-- ============================================================

-- Add QR code public URL column (stores Supabase Storage public URL)
-- Populated by the background task after registration
ALTER TABLE members ADD COLUMN IF NOT EXISTS qr_url TEXT;

-- Verify the column was added
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'members' AND column_name = 'qr_url';
