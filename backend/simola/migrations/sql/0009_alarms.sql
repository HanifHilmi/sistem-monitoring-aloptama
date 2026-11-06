-- R3.1: AWOS alarms (FR-ING-008, FR-ALM-001…004).
--
-- Each CDP runs its own alarm detection and writes its own alarm file, so the same alarm is usually logged by
-- both, seconds apart. alarm_source_row keeps every CDP's rows as read (re-reading a file adds nothing);
-- alarm_event is the merged list the screens show, rebuilt per alarm name from the source rows.

CREATE TABLE alarm_name (
    system_id       smallint NOT NULL REFERENCES system (id),
    name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    -- Where the alarm is shown (E12): one sensor, a whole site, the station, or not assigned yet.
    place_kind      text NOT NULL CHECK (place_kind IN ('component', 'site', 'station', 'unmapped')),
    site_id         smallint REFERENCES site (id),
    component_type  text,
    -- seed: set from the name when it was first seen (D4); admin: changed in Admin → Alarm mapping (audited).
    source          text NOT NULL CHECK (source IN ('seed', 'admin')),
    first_seen      timestamptz NOT NULL DEFAULT now(),
    updated_by      text,
    updated_at      timestamptz,
    PRIMARY KEY (system_id, name),
    FOREIGN KEY (site_id, component_type) REFERENCES component (site_id, type_code),
    CHECK ((place_kind IN ('component', 'site')) = (site_id IS NOT NULL)),
    CHECK ((place_kind = 'component') = (component_type IS NOT NULL))
);

CREATE TABLE alarm_source_row (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id    smallint NOT NULL,
    cdp_id       smallint NOT NULL REFERENCES cdp_node (id),
    time         timestamptz NOT NULL,
    name         text NOT NULL,
    type         text NOT NULL CHECK (type IN ('error', 'warning')),
    state        text NOT NULL CHECK (length(state) BETWEEN 1 AND 40),
    active       boolean NOT NULL,
    message      text NOT NULL CHECK (length(message) <= 500),
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (system_id, name) REFERENCES alarm_name (system_id, name),
    UNIQUE (cdp_id, time, name, type, state, active, message)
);
CREATE INDEX alarm_source_row_name ON alarm_source_row (system_id, name, time);

CREATE TABLE alarm_event (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id  smallint NOT NULL,
    time       timestamptz NOT NULL,  -- the earliest of the CDPs' times
    name       text NOT NULL,
    type       text NOT NULL CHECK (type IN ('error', 'warning')),
    state      text NOT NULL,
    active     boolean NOT NULL,
    -- This change raised the alarm, as opposed to acknowledging one that was already raised.
    raised     boolean NOT NULL,
    message    text NOT NULL,
    cdp_ids    smallint[] NOT NULL CHECK (cardinality(cdp_ids) > 0),
    FOREIGN KEY (system_id, name) REFERENCES alarm_name (system_id, name)
);
CREATE INDEX alarm_event_time ON alarm_event (system_id, time);
CREATE INDEX alarm_event_name ON alarm_event (system_id, name, time);
