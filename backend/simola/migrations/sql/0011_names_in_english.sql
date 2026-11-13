-- System, site, sensor and parameter names read the same in both languages (Product Owner, 2026-11-13): the
-- Indonesian screens keep the English names ("Runway 04", "Present Weather Sensor", "Density altitude"), as the
-- technicians and the AWOS itself use them. Word-for-word translations caused confusion.
UPDATE system_type SET name_id = name_en WHERE name_id <> name_en;
UPDATE system SET name_id = name_en WHERE name_id <> name_en;
UPDATE site SET name_id = name_en WHERE name_id <> name_en;
UPDATE component_type SET name_id = name_en WHERE name_id <> name_en;
UPDATE metric_field SET name_id = name_en WHERE name_id <> name_en;
