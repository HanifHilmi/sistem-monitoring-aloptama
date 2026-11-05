-- R2.4: validity rules and detections (PRD FR-DQ-001..005, FR-DSH-009/010, OPEN-08; docs/design/r2.md §4.4).
-- Additive, except that job.type now also allows 'detect', which earlier code never creates (NFR-OPS-002).

ALTER TABLE job DROP CONSTRAINT job_type_check;
ALTER TABLE job ADD CONSTRAINT job_type_check
    CHECK (type IN ('reprocess', 'recompute', 'import_legacy', 'detect'));

-- A rule checks one field of a component type: range, stuck or spike. Its parameters, scope and on/off state live
-- in versions; a change makes a new version and old detections keep theirs (PRD E8).
CREATE TABLE dq_rule (
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id            smallint NOT NULL REFERENCES system (id),
    component_type_code  text NOT NULL REFERENCES component_type (code),
    field_code           text NOT NULL,
    type                 text NOT NULL CHECK (type IN ('range', 'stuck', 'spike')),
    proposed             boolean NOT NULL DEFAULT false,   -- proposed from the history, not yet approved (OPEN-08)
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dq_rule_version (
    rule_id     integer NOT NULL REFERENCES dq_rule (id),
    version     integer NOT NULL CHECK (version >= 1),
    site_id     smallint REFERENCES site (id),             -- NULL: every site with the component type
    params      jsonb NOT NULL,
    enabled     boolean NOT NULL,
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, version)
);

-- A stretch a rule found: suspect until an Admin confirms or rejects it (FR-DQ-004). A confirmed detection on a
-- mandatory field also has rows in invalid_interval (R2.3), which is what the figures read.
CREATE TABLE dq_detection (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rule_id       integer NOT NULL,
    rule_version  integer NOT NULL,
    component_id  integer NOT NULL REFERENCES component (id),
    field_code    text NOT NULL,
    type          text NOT NULL CHECK (type IN ('range', 'stuck', 'spike')),
    params        jsonb NOT NULL,                          -- the rule's parameters when it fired (FR-DQ-003)
    start_at      timestamptz NOT NULL,
    end_at        timestamptz NOT NULL,                    -- exclusive
    evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,
    status        text NOT NULL DEFAULT 'suspect' CHECK (status IN ('suspect', 'confirmed', 'rejected')),
    decided_by    text,
    decided_at    timestamptz,
    note          text CHECK (note IS NULL OR length(note) <= 500),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (rule_id, rule_version) REFERENCES dq_rule_version (rule_id, version),
    CHECK (start_at < end_at)
);
CREATE INDEX dq_detection_queue ON dq_detection (status, start_at DESC);
CREATE INDEX dq_detection_component ON dq_detection (component_id, start_at);
CREATE INDEX dq_detection_rule ON dq_detection (rule_id, rule_version, component_id, start_at);

-- What a field's whole history looks like (OPEN-08): stored because it takes seconds to work out.
CREATE TABLE dq_field_history (
    system_id            smallint NOT NULL REFERENCES system (id),
    component_type_code  text NOT NULL REFERENCES component_type (code),
    field_code           text NOT NULL,
    computed_at          timestamptz NOT NULL DEFAULT now(),
    stats                jsonb NOT NULL,
    PRIMARY KEY (system_id, component_type_code, field_code)
);
