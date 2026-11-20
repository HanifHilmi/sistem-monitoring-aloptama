-- R3.7: a sensor's physical parts (FR-REG-004 as changed in PRD v1.5). A sensor (component) is what counts for
-- availability; its parts are the units on the mast, each with its own part and serial number: the
-- thermohygrometer and its MARS, the barometer and its quadplate, the RVR's transmitters and receivers.
-- Replacing a part closes the old row (removed_on) and adds the new one with ``replaces`` pointing back, so the
-- history of what was installed when is kept forever. Every change is audited by the API.

CREATE TABLE component_part (
    id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_id   integer NOT NULL REFERENCES component (id),
    role           text NOT NULL CHECK (length(btrim(role)) BETWEEN 1 AND 60),  -- "Receiver 2"; English name
    manufacturer   text CHECK (manufacturer IS NULL OR length(manufacturer) <= 100),
    model          text CHECK (model IS NULL OR length(model) <= 100),
    part_number    text CHECK (part_number IS NULL OR length(part_number) <= 100),     -- signed-in users only
    serial_number  text CHECK (serial_number IS NULL OR length(serial_number) <= 100), -- signed-in users only
    firmware       text CHECK (firmware IS NULL OR length(firmware) <= 100),
    installed_on   date,                                                    -- UTC
    removed_on     date,                                                    -- UTC; null while installed
    removed_reason text CHECK (removed_reason IS NULL OR length(removed_reason) <= 500),
    replaces       integer REFERENCES component_part (id),
    notes          text CHECK (notes IS NULL OR length(notes) <= 500),
    created_by     text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_by     text,
    updated_at     timestamptz,
    CHECK (removed_on IS NULL OR installed_on IS NULL OR removed_on >= installed_on)
);
CREATE INDEX component_part_component ON component_part (component_id, id);
-- a part is replaced at most once
CREATE UNIQUE INDEX component_part_replaces ON component_part (replaces) WHERE replaces IS NOT NULL;

-- The part a calibration covered, when the certificate names one; null for the sensor as a whole.
ALTER TABLE calibration_record ADD COLUMN part_id integer REFERENCES component_part (id);

-- Each sensor's details as recorded so far become its first part, named after the sensor's main unit. An RVR's
-- record described the whole visibility sensor, so it becomes "Visibility sensor"; an Admin renames it to the
-- unit that carries that serial number. Calibrations keep part_id null (the sensor as a whole), as recorded.
-- The old columns on component stay for one release, so the previous release still runs (NFR-OPS-002); SIMOLA
-- no longer reads or writes them.
INSERT INTO component_part (component_id, role, manufacturer, model, part_number, serial_number, firmware,
                            installed_on, created_by)
SELECT c.id,
       CASE c.type_code
           WHEN 'DCP'  THEN 'Data logger'
           WHEN 'ATRH' THEN 'Thermohygrometer'
           WHEN 'BARO' THEN 'Barometer'
           WHEN 'ANEM' THEN 'Wind sensor'
           WHEN 'RVR'  THEN 'Visibility sensor'
           WHEN 'CEL'  THEN 'Ceilometer'
           WHEN 'PWX'  THEN 'Present weather sensor'
           WHEN 'RAIN' THEN 'Rain gauge'
           WHEN 'SOLR' THEN 'Pyranometer'
           WHEN 'LIGH' THEN 'Lightning detector'
           ELSE c.type_code
       END,
       c.manufacturer, c.model, c.part_number, c.serial_number, c.firmware, c.installed_on, 'migration'
FROM component c
WHERE coalesce(c.manufacturer, c.model, c.part_number, c.serial_number, c.firmware) IS NOT NULL
ORDER BY c.id;
