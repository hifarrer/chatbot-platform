-- Migration to add profile fields to user table
-- Run this SQL to add the new fields to your database

-- Add new columns to the user table
ALTER TABLE "user" ADD COLUMN full_name VARCHAR(100);
ALTER TABLE "user" ADD COLUMN business_name VARCHAR(100);
ALTER TABLE "user" ADD COLUMN website VARCHAR(255);

-- Add comments for documentation
COMMENT ON COLUMN "user".full_name IS 'User full name for profile display';
COMMENT ON COLUMN "user".business_name IS 'User business or company name';
COMMENT ON COLUMN "user".website IS 'User website URL';

-- Optional: Update existing users with default values if needed
-- UPDATE "user" SET full_name = username WHERE full_name IS NULL;
-- UPDATE "user" SET business_name = 'Individual' WHERE business_name IS NULL;
