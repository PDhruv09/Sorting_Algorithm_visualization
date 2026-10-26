-- Run as the Entra administrator, AFTER azure_schema_v1.sql succeeds.
-- The external user was created earlier; this script does not create identities.
GRANT CONNECT TO [sorting-visualizer-db-identity];
ALTER USER [sorting-visualizer-db-identity] WITH DEFAULT_SCHEMA = dbo;
GRANT SELECT ON OBJECT::dbo.challenge_schema TO [sorting-visualizer-db-identity];
GRANT SELECT ON OBJECT::dbo.students TO [sorting-visualizer-db-identity];
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.attempts TO [sorting-visualizer-db-identity];
GRANT SELECT, INSERT, DELETE ON OBJECT::dbo.sessions TO [sorting-visualizer-db-identity];
-- No db_owner, table creation, student-list writes, or attempt deletion privileges.

-- Manage real roster entries privately in Azure as the database administrator.
-- Do not save student email addresses in this repository or container image.
