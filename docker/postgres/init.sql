-- Runs once when the Docker Compose PostgreSQL volume is first created.
-- The main `peaksift` database is created by POSTGRES_DB; this adds the test database.
CREATE DATABASE peaksift_test;
