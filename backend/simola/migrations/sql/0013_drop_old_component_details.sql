-- R3.11: the second half of R3.7's change (NFR-OPS-002, expand then contract). A sensor's manufacturer, model,
-- part and serial numbers and firmware are kept on its parts (component_part, migration 0012). The old columns on
-- component have not been read or written since R3.7, so the release before this one runs without them. (Its own
-- migrate step still refuses a database that has this file: rollbacks run on a newer database only from R3.11 on,
-- see docs/runbooks/deploy.md, Rollback.)
--
-- Safety first: if a sensor still has details in the old columns but no part at all, 0012 did not carry them over.
-- Then this migration stops, drops nothing, and the deploy fails with the sensors named.
--
-- Dropping a column briefly locks the whole table, and the running release keeps working while this runs. If a long
-- transaction holds component, give up after 30 s (the deploy fails, nothing changes; deploy again) instead of
-- making every query on component wait behind the lock.
SET LOCAL lock_timeout = '30s';

DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(st.slug || ':' || c.type_code, ', ' ORDER BY c.id) INTO missing
    FROM component c
    JOIN site st ON st.id = c.site_id
    WHERE coalesce(c.manufacturer, c.model, c.part_number, c.serial_number, c.firmware) IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM component_part p WHERE p.component_id = c.id);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'sensors % have details in the old columns but no part; nothing dropped', missing;
    END IF;
END
$$;

ALTER TABLE component
    DROP COLUMN manufacturer,
    DROP COLUMN model,
    DROP COLUMN part_number,
    DROP COLUMN serial_number,
    DROP COLUMN firmware;
