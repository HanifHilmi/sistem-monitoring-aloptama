-- R2.3: manual flags (PRD FR-DQ-006/007, FR-KPI-006/008/009; docs/design/r2.md §4.3).
-- Additive only: R1 and R2.2 code run unchanged against this schema (NFR-OPS-002).

-- (component_id, during) in one GiST index needs the btree operator classes for the integer column.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- A time range an Admin marked as bad data on one or more components. Never deleted: removing a flag sets
-- removed_at, and every change is in the audit log.
CREATE TABLE flag (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id   smallint NOT NULL REFERENCES system (id),
    start_at    timestamptz NOT NULL CHECK (start_at = date_trunc('minute', start_at)),
    end_at      timestamptz NOT NULL CHECK (end_at = date_trunc('minute', end_at)),   -- exclusive
    reason      text NOT NULL
                CHECK (reason IN ('sensor_fault', 'maintenance', 'calibration', 'environmental', 'other')),
    note        text NOT NULL CHECK (length(btrim(note)) BETWEEN 3 AND 500),
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text,
    updated_at  timestamptz,
    removed_by  text,
    removed_at  timestamptz,
    CHECK (start_at < end_at)
);
CREATE INDEX flag_system_start ON flag (system_id, start_at DESC);

CREATE TABLE flag_component (
    flag_id       bigint NOT NULL REFERENCES flag (id),
    component_id  integer NOT NULL REFERENCES component (id),
    PRIMARY KEY (flag_id, component_id)
);

-- The minutes that do not count for a component (the "no invalidating interval" part of component validity):
-- active flags now, confirmed detections on a mandatory field from R2.4. Written in the same transaction as the
-- flag or detection it comes from; a removed flag has no rows here. DCPs never appear (the API refuses them and
-- the engine ignores them).
CREATE TABLE invalid_interval (
    component_id  integer NOT NULL REFERENCES component (id),
    during        tstzrange NOT NULL CHECK (NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)),
    source        text NOT NULL CHECK (source IN ('flag', 'detection')),
    source_id     bigint NOT NULL,
    PRIMARY KEY (source, source_id, component_id)
);
CREATE INDEX invalid_interval_during ON invalid_interval USING gist (component_id, during);
