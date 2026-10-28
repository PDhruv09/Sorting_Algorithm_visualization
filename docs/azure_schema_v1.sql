-- Run manually as the Entra administrator in sorting-challenge-db.
-- This creates empty tables. It does not copy or delete local attempts.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID(N'dbo.challenge_schema', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.challenge_schema (
        singleton int NOT NULL PRIMARY KEY CHECK (singleton = 1),
        version int NOT NULL
    );
END;
IF EXISTS (SELECT 1 FROM dbo.challenge_schema WHERE version <> 1)
    THROW 50001, 'Unsupported schema version; no changes applied.', 1;
IF NOT EXISTS (SELECT 1 FROM dbo.challenge_schema WHERE singleton = 1)
BEGIN
    -- Existing unversioned tables must be inspected, never silently adopted.
    IF OBJECT_ID(N'dbo.students', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.attempts', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.sessions', N'U') IS NOT NULL
        THROW 50002, 'Unversioned challenge tables already exist.', 1;
    CREATE TABLE dbo.students (
        email varchar(254) NOT NULL PRIMARY KEY,
        role varchar(20) NOT NULL DEFAULT 'student',
        enabled bit NOT NULL DEFAULT 1,
        created_at varchar(40) NOT NULL
    );
    CREATE TABLE dbo.attempts (
        id varchar(32) NOT NULL PRIMARY KEY,
        student_email varchar(254) NOT NULL REFERENCES dbo.students(email),
        test_version varchar(64) NOT NULL,
        attempt_number int NOT NULL DEFAULT 1,
        status varchar(20) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted')),
        current_index int NOT NULL DEFAULT 0,
        revision int NOT NULL DEFAULT 0,
        questions nvarchar(max) NOT NULL CHECK (ISJSON(questions) = 1),
        answers nvarchar(max) NOT NULL DEFAULT N'{}' CHECK (ISJSON(answers) = 1),
        feedback nvarchar(max) NULL,
        score int NULL,
        started_at varchar(40) NOT NULL,
        submitted_at varchar(40) NULL,
        UNIQUE(student_email, test_version, attempt_number)
    );
    CREATE TABLE dbo.sessions (
        token_hash varchar(64) NOT NULL PRIMARY KEY,
        attempt_id varchar(32) NOT NULL REFERENCES dbo.attempts(id),
        expires_at float NOT NULL
    );
    CREATE INDEX sessions_expiry ON dbo.sessions(expires_at);
    CREATE INDEX sessions_attempt ON dbo.sessions(attempt_id);
    INSERT INTO dbo.challenge_schema(singleton, version) VALUES (1, 1);
END;
COMMIT;
