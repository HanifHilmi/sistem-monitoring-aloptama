-- R2.1: accounts, sessions and the audit log (PRD FR-AUTH-001..007, FR-AUD-001; docs/design/r2.md §4.1-4.2).
-- Additive only: R1 code runs unchanged against this schema (NFR-OPS-002).

CREATE TABLE app_user (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username              text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,31}$'),
    display_name          text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 100),
    email                 text CHECK (email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
    role                  text NOT NULL CHECK (role IN ('viewer', 'admin')),
    active                boolean NOT NULL DEFAULT true,
    password_hash         text NOT NULL,                  -- Argon2id (FR-AUTH-003)
    must_change_password  boolean NOT NULL DEFAULT true,  -- set by an Admin's new account or reset
    locked_until          timestamptz,                    -- after repeated failed sign-ins (FR-AUTH-004)
    failures_reset_at     timestamptz NOT NULL DEFAULT now(), -- failed sign-ins before this no longer count
    last_login_at         timestamptz,
    password_changed_at   timestamptz NOT NULL DEFAULT now(),
    created_at            timestamptz NOT NULL DEFAULT now(),
    created_by            text NOT NULL
);

-- Server-side sessions (FR-AUTH-002). Only a SHA-256 of the cookie's token is stored.
CREATE TABLE user_session (
    token_hash    bytea PRIMARY KEY,
    user_id       integer NOT NULL REFERENCES app_user (id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,                   -- absolute lifetime; idle time uses last_seen_at
    source_ip     text,
    user_agent    text
);
CREATE INDEX user_session_user ON user_session (user_id);

-- Append-only audit log (FR-AUD-001). The application role also loses UPDATE, DELETE and TRUNCATE on it
-- (migrations/runner.py, ensure_app_role); these triggers stop every role, the owner included.
CREATE TABLE audit_event (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    time         timestamptz NOT NULL DEFAULT now(),
    actor        text,                                    -- username, 'cli', or NULL (anonymous sign-in attempt)
    action       text NOT NULL,
    entity_type  text,
    entity_id    text,
    before       jsonb,
    after        jsonb,
    source_ip    text
);
CREATE INDEX audit_event_time ON audit_event (time DESC, id DESC);
-- Failed sign-ins per account and per address over the last 15 minutes (FR-AUTH-004).
CREATE INDEX audit_event_failed_user ON audit_event (entity_id, time) WHERE action = 'login_failed';
CREATE INDEX audit_event_failed_ip ON audit_event (source_ip, time) WHERE action = 'login_failed';

CREATE FUNCTION audit_event_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only' USING ERRCODE = 'insufficient_privilege';
END;
$$;
CREATE TRIGGER audit_event_no_change BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_append_only();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_event
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_append_only();
