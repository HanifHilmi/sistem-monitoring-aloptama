-- R3.2: METAR/SPECI, MET REPORT/SPECIAL and TAF as the AWOS issued them (FR-ING-009, FR-RPT-001…003).
--
-- Each CDP logs the reports it sends, so the same report is usually in both CDPs' logs, up to two minutes apart.
-- report_source_row keeps every CDP's lines as read (re-reading a file adds nothing); report_entry is the list the
-- screens show: one row per report, with the CDPs that logged it, rebuilt per report text from the source rows.

CREATE TABLE report_source_row (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id    smallint NOT NULL REFERENCES system (id),
    cdp_id       smallint NOT NULL REFERENCES cdp_node (id),
    type         text NOT NULL CHECK (type IN ('metar', 'metreport', 'taf')),
    kind         text NOT NULL CHECK (length(kind) BETWEEN 1 AND 20),
    logged_at    timestamptz NOT NULL,
    text         text NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
    notes        text[] NOT NULL DEFAULT '{}',  -- the AWOS's own notes after the report, e.g. why a SPECI was sent
    runway       text,                          -- runway in use, from the note "(04)"
    bulletin     text,                          -- TAF: the bulletin heading, e.g. "FTID32 WIDN 071100"
    ingested_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX report_source_row_key ON report_source_row (cdp_id, type, logged_at, md5(text));
CREATE INDEX report_source_row_text ON report_source_row (system_id, type, md5(text));

CREATE TABLE report_entry (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id  smallint NOT NULL REFERENCES system (id),
    type       text NOT NULL CHECK (type IN ('metar', 'metreport', 'taf')),
    kind       text NOT NULL,
    logged_at  timestamptz NOT NULL,  -- the earliest of the CDPs' times
    text       text NOT NULL,
    notes      text[] NOT NULL DEFAULT '{}',
    runway     text,
    bulletin   text,
    cdp_ids    smallint[] NOT NULL CHECK (cardinality(cdp_ids) > 0)
);
CREATE INDEX report_entry_time ON report_entry (system_id, type, logged_at);
CREATE INDEX report_entry_text ON report_entry (system_id, type, md5(text));
