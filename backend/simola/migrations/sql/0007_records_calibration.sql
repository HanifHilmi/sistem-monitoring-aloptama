-- R2.5: station, site and sensor records and calibration (PRD FR-REG-004/005, FR-DSH-010, FR-ADM-003;
-- docs/design/r2.md §4.5). Additive only: earlier code ignores the new columns and table (NFR-OPS-002).

ALTER TABLE system
    ADD COLUMN wmo_number        text CHECK (wmo_number IS NULL OR wmo_number ~ '^[0-9]{5}$'),
    ADD COLUMN airport_name      text CHECK (airport_name IS NULL OR length(airport_name) <= 120),
    ADD COLUMN lat               double precision CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
    ADD COLUMN lon               double precision CHECK (lon IS NULL OR lon BETWEEN -180 AND 180),
    ADD COLUMN elevation_m       double precision,
    ADD COLUMN procurement_year  smallint CHECK (procurement_year IS NULL OR procurement_year BETWEEN 1950 AND 2100),
    ADD COLUMN notes             text CHECK (notes IS NULL OR length(notes) <= 500);

ALTER TABLE site
    ADD COLUMN lat                    double precision CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
    ADD COLUMN lon                    double precision CHECK (lon IS NULL OR lon BETWEEN -180 AND 180),
    ADD COLUMN elevation_m            double precision,
    ADD COLUMN threshold_elevation_m  double precision,
    ADD COLUMN description            text CHECK (description IS NULL OR length(description) <= 500);

-- Serial and part numbers are for signed-in users only (PRD §5.4, OPEN-13): the API leaves them out for the public.
ALTER TABLE component
    ADD COLUMN sensor_type    text CHECK (sensor_type IS NULL OR length(sensor_type) <= 100),
    ADD COLUMN manufacturer   text CHECK (manufacturer IS NULL OR length(manufacturer) <= 100),
    ADD COLUMN model          text CHECK (model IS NULL OR length(model) <= 100),
    ADD COLUMN part_number    text CHECK (part_number IS NULL OR length(part_number) <= 100),
    ADD COLUMN serial_number  text CHECK (serial_number IS NULL OR length(serial_number) <= 100),
    ADD COLUMN installed_on   date,
    ADD COLUMN firmware       text CHECK (firmware IS NULL OR length(firmware) <= 100),
    ADD COLUMN notes          text CHECK (notes IS NULL OR length(notes) <= 500);

-- A sensor's calibrations. The status (OK, due soon, overdue, unknown) is worked out on read from the latest record
-- that was not removed. Removing keeps the row (kept forever, PRD §9.6) and is audited.
CREATE TABLE calibration_record (
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_id     integer NOT NULL REFERENCES component (id),
    date             date NOT NULL,                       -- UTC
    performed_by     text NOT NULL CHECK (length(btrim(performed_by)) BETWEEN 1 AND 100),
    certificate      text CHECK (certificate IS NULL OR length(certificate) <= 100),
    next_due         date NOT NULL,
    interval_months  smallint CHECK (interval_months IS NULL OR interval_months BETWEEN 1 AND 120),
    notes            text CHECK (notes IS NULL OR length(notes) <= 500),
    created_by       text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_by       text,
    updated_at       timestamptz,
    removed_by       text,
    removed_at       timestamptz,
    CHECK (next_due > date)
);
CREATE INDEX calibration_record_component ON calibration_record (component_id, date DESC, id DESC);

INSERT INTO setting (key, value) VALUES ('calibration_due_soon_days', '30') ON CONFLICT (key) DO NOTHING;
