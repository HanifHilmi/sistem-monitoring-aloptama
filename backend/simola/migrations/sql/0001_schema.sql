-- SIMOLA initial schema (PRD §9). Immutable once applied: add new files for changes.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Registry (FR-REG-001/002/003/006/007)
-- ---------------------------------------------------------------------------
CREATE TABLE system_type (
    code         text PRIMARY KEY,
    name_en      text NOT NULL,
    name_id      text NOT NULL,
    kpi_profile  text NOT NULL CHECK (kpi_profile IN ('sla_ola', 'uptime_validity'))
);

CREATE TABLE system (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            text NOT NULL UNIQUE,
    type_code       text NOT NULL REFERENCES system_type (code),
    name_en         text NOT NULL,
    name_id         text NOT NULL,
    icao            text CHECK (icao ~ '^[A-Z]{4}$'),
    coverage_start  timestamptz NOT NULL,
    sort            smallint NOT NULL DEFAULT 0
);

CREATE TABLE cdp_node (
    id          smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id   smallint NOT NULL REFERENCES system (id),
    code        text NOT NULL,
    preference  smallint NOT NULL,
    UNIQUE (system_id, code),
    UNIQUE (system_id, preference)
);

CREATE TABLE site (
    id            smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id     smallint NOT NULL REFERENCES system (id),
    code          text NOT NULL,
    station_code  text NOT NULL,
    slug          text NOT NULL CHECK (slug ~ '^[a-z0-9-]+$'),
    name_en       text NOT NULL,
    name_id       text NOT NULL,
    sort          smallint NOT NULL DEFAULT 0,
    UNIQUE (system_id, code),
    UNIQUE (system_id, slug),
    UNIQUE (system_id, station_code)
);

CREATE TABLE component_type (
    code     text PRIMARY KEY,
    name_en  text NOT NULL,
    name_id  text NOT NULL,
    is_dcp   boolean NOT NULL DEFAULT false,
    sort     smallint NOT NULL DEFAULT 0
);

CREATE TABLE metric_field (
    system_type_code  text NOT NULL REFERENCES system_type (code),
    code              text NOT NULL,
    column_name       text NOT NULL CHECK (column_name ~ '^[a-z][a-z0-9_]*$'),
    value_type        text NOT NULL CHECK (value_type IN ('numeric', 'text')),
    unit              text,
    name_en           text NOT NULL,
    name_id           text NOT NULL,
    sort              smallint NOT NULL DEFAULT 0,
    PRIMARY KEY (system_type_code, code),
    UNIQUE (system_type_code, column_name)
);

CREATE TABLE component (
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site_id          smallint NOT NULL REFERENCES site (id),
    type_code        text NOT NULL REFERENCES component_type (code),
    sort             smallint NOT NULL DEFAULT 0,
    in_service_from  timestamptz,
    in_service_to    timestamptz,
    CHECK (in_service_from IS NULL OR in_service_to IS NULL OR in_service_from < in_service_to),
    UNIQUE (site_id, type_code)
);

-- Which fields a component reports at its site (RVR at RWY 04 has ALS and D/N; RWY 22 does not).
CREATE TABLE component_field (
    component_id      integer NOT NULL REFERENCES component (id) ON DELETE CASCADE,
    system_type_code  text NOT NULL,
    field_code        text NOT NULL,
    PRIMARY KEY (component_id, field_code),
    FOREIGN KEY (system_type_code, field_code) REFERENCES metric_field (system_type_code, code)
);

-- Mandatory fields decide component validity (FR-REG-003, decision B4a). Admin-editable from R2.
CREATE TABLE mandatory_field (
    system_type_code     text NOT NULL,
    component_type_code  text NOT NULL REFERENCES component_type (code),
    field_code           text NOT NULL,
    PRIMARY KEY (system_type_code, component_type_code, field_code),
    FOREIGN KEY (system_type_code, field_code) REFERENCES metric_field (system_type_code, code)
);

CREATE TABLE setting (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL DEFAULT 'system'
);

-- ---------------------------------------------------------------------------
-- AWOS CAT.III time series (PRD §9.4)
-- ---------------------------------------------------------------------------
-- One parsed minute from one CDP's 1-minute file, per site (FR-ING-003).
CREATE TABLE awos_cat3_source_minute (
    time             timestamptz NOT NULL,
    cdp_id           smallint NOT NULL REFERENCES cdp_node (id),
    site_id          smallint NOT NULL REFERENCES site (id),
    all_missing      boolean NOT NULL,
    temp_c           double precision,
    dewp_c           double precision,
    rh_pct           double precision,
    qnh_hpa          double precision,
    da_ft            double precision,
    wind_speed_kt    double precision,
    wind_dir_deg     double precision,
    gust_speed_kt    double precision,
    gust_dir_deg     double precision,
    rvr_m            double precision,
    vis_m            double precision,
    als_cd           double precision,
    als_dn           text,
    rls              double precision,
    lr1_100ft        double precision,
    sky_condition    text,
    precip_mm        double precision,
    present_weather  text,
    solar_wm2        double precision,
    lightning        text,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cdp_id, site_id, time)
);
SELECT create_hypertable('awos_cat3_source_minute', by_range('time', INTERVAL '7 days'));

-- The merged minute used for KPIs and charts (FR-ING-005).
CREATE TABLE awos_cat3_minute (
    time             timestamptz NOT NULL,
    site_id          smallint NOT NULL REFERENCES site (id),
    all_missing      boolean NOT NULL,
    temp_c           double precision,
    dewp_c           double precision,
    rh_pct           double precision,
    qnh_hpa          double precision,
    da_ft            double precision,
    wind_speed_kt    double precision,
    wind_dir_deg     double precision,
    gust_speed_kt    double precision,
    gust_dir_deg     double precision,
    rvr_m            double precision,
    vis_m            double precision,
    als_cd           double precision,
    als_dn           text,
    rls              double precision,
    lr1_100ft        double precision,
    sky_condition    text,
    precip_mm        double precision,
    present_weather  text,
    solar_wm2        double precision,
    lightning        text,
    source_cdp_id    smallint NOT NULL REFERENCES cdp_node (id),
    cdp_disagree     boolean NOT NULL DEFAULT false,
    PRIMARY KEY (site_id, time)
);
SELECT create_hypertable('awos_cat3_minute', by_range('time', INTERVAL '7 days'));

-- Data flow and network reachability per CDP per minute (FR-ING-004/007).
CREATE TABLE cdp_minute_fact (
    time              timestamptz NOT NULL,
    cdp_id            smallint NOT NULL REFERENCES cdp_node (id),
    data_flow         boolean NOT NULL DEFAULT false,
    probes_attempted  smallint NOT NULL DEFAULT 0 CHECK (probes_attempted >= 0),
    probes_ok         smallint NOT NULL DEFAULT 0 CHECK (probes_ok >= 0 AND probes_ok <= probes_attempted),
    rtt_min_ms        real,
    probe_method      text,
    last_error        text,
    PRIMARY KEY (cdp_id, time)
);
SELECT create_hypertable('cdp_minute_fact', by_range('time', INTERVAL '7 days'));

-- Compression after 7 days; no retention policy (decision E1: keep forever).
ALTER TABLE awos_cat3_source_minute SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'cdp_id, site_id',
    timescaledb.compress_orderby = 'time DESC'
);
ALTER TABLE awos_cat3_minute SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'site_id',
    timescaledb.compress_orderby = 'time DESC'
);
ALTER TABLE cdp_minute_fact SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'cdp_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('awos_cat3_source_minute', INTERVAL '7 days');
SELECT add_compression_policy('awos_cat3_minute', INTERVAL '7 days');
SELECT add_compression_policy('cdp_minute_fact', INTERVAL '7 days');

-- ---------------------------------------------------------------------------
-- Daily rollups (PRD §9.4) and their dirty-day queue
-- ---------------------------------------------------------------------------
CREATE TABLE availability_daily (
    scope_type   text NOT NULL CHECK (scope_type IN ('sla', 'cdp_flow', 'cdp_reach', 'cdp_legacy', 'component')),
    scope_id     integer NOT NULL,
    day          date NOT NULL,
    valid        integer NOT NULL CHECK (valid >= 0),
    expected     integer NOT NULL CHECK (expected >= 0 AND valid <= expected),
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope_type, scope_id, day)
);

CREATE TABLE rollup_dirty (
    system_id  smallint NOT NULL REFERENCES system (id),
    day        date NOT NULL,
    marked_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (system_id, day)
);

-- ---------------------------------------------------------------------------
-- Operations: ingestion status, jobs, worker heartbeat, backups
-- ---------------------------------------------------------------------------
CREATE TABLE ingest_status (
    source            text PRIMARY KEY,
    system_id         smallint NOT NULL REFERENCES system (id),
    cdp_id            smallint REFERENCES cdp_node (id),
    available         boolean NOT NULL DEFAULT false,
    last_attempt_at   timestamptz,
    last_success_at   timestamptz,
    last_record_time  timestamptz,
    oldest_file_date  date,
    parse_warnings    bigint NOT NULL DEFAULT 0,
    last_error        text,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type         text NOT NULL CHECK (type IN ('reprocess', 'recompute', 'import_legacy')),
    params       jsonb NOT NULL DEFAULT '{}'::jsonb,
    status       text NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled', 'interrupted')),
    progress     real NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    message      text,
    log          text NOT NULL DEFAULT '',
    created_by   text NOT NULL DEFAULT 'cli',
    created_at   timestamptz NOT NULL DEFAULT now(),
    started_at   timestamptz,
    finished_at  timestamptz
);
CREATE INDEX job_status_idx ON job (status, created_at);
-- At most one active reprocess job at a time (FR-ING-010).
CREATE UNIQUE INDEX job_one_active_reprocess ON job (type) WHERE type = 'reprocess' AND status IN ('queued', 'running');

CREATE TABLE worker_heartbeat (
    worker     text PRIMARY KEY,
    version    text NOT NULL,
    leader     boolean NOT NULL,
    last_beat  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE backup_run (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz,
    ok           boolean,
    size_bytes   bigint,
    file_name    text,
    message      text
);
