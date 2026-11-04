-- Registry seed for AWOS CAT.III WIDN (PRD §9.2) and default settings.
-- CDP addresses and share paths are deployment configuration (SIMOLA_CDP_*), not data.

INSERT INTO system_type (code, name_en, name_id, kpi_profile)
VALUES ('AWOS_CAT3', 'AWOS CAT.III', 'AWOS KAT. III', 'sla_ola');

-- Coverage starts at the first record of the earliest CDP 1-minute file (FR-REG-007).
INSERT INTO system (code, type_code, name_en, name_id, icao, coverage_start, sort)
VALUES ('WIDN-CAT3', 'AWOS_CAT3', 'AWOS CAT.III WIDN', 'AWOS KAT. III WIDN', 'WIDN', '2025-12-24 03:40:00+00', 1);

INSERT INTO cdp_node (system_id, code, preference)
SELECT s.id, v.code, v.pref
FROM system s, (VALUES ('CDP1', 1), ('CDP2', 2)) AS v(code, pref)
WHERE s.code = 'WIDN-CAT3';

INSERT INTO site (system_id, code, station_code, slug, name_en, name_id, sort)
SELECT s.id, v.code, v.station, v.slug, v.name_en, v.name_id, v.sort
FROM system s, (VALUES
    ('RWY04',  '04', '04',     'Runway 04',     'Landasan 04',     1),
    ('RWYMID', 'M',  'middle', 'Runway Middle', 'Landasan Tengah', 2),
    ('RWY22',  '22', '22',     'Runway 22',     'Landasan 22',     3)
) AS v(code, station, slug, name_en, name_id, sort)
WHERE s.code = 'WIDN-CAT3';

INSERT INTO component_type (code, name_en, name_id, is_dcp, sort) VALUES
    ('DCP',  'Data Collection Platform',   'Data Collection Platform',  true,  1),
    ('ATRH', 'Air Temperature & Humidity', 'Suhu & Kelembapan Udara',   false, 2),
    ('BARO', 'Barometer',                  'Barometer',                 false, 3),
    ('ANEM', 'Anemometer',                 'Anemometer',                false, 4),
    ('RVR',  'Runway Visual Range',        'Runway Visual Range',       false, 5),
    ('CEL',  'Ceilometer',                 'Ceilometer',                false, 6),
    ('PWX',  'Present Weather Sensor',     'Sensor Cuaca Saat Ini',     false, 7),
    ('RAIN', 'Rain Gauge',                 'Penakar Hujan',             false, 8),
    ('SOLR', 'Solar Radiation Sensor',     'Sensor Radiasi Matahari',   false, 9),
    ('LIGH', 'Lightning Detector',         'Detektor Petir',            false, 10);

INSERT INTO metric_field (system_type_code, code, column_name, value_type, unit, name_en, name_id, sort) VALUES
    ('AWOS_CAT3', 'TEMP', 'temp_c',          'numeric', '°C',     'Air temperature',       'Suhu udara',                 1),
    ('AWOS_CAT3', 'DEWP', 'dewp_c',          'numeric', '°C',     'Dew point',             'Titik embun',                2),
    ('AWOS_CAT3', 'RH',   'rh_pct',          'numeric', '%',      'Relative humidity',     'Kelembapan relatif',         3),
    ('AWOS_CAT3', 'QNH',  'qnh_hpa',         'numeric', 'hPa',    'QNH',                   'QNH',                        4),
    ('AWOS_CAT3', 'DA',   'da_ft',           'numeric', 'ft',     'Density altitude',      'Ketinggian densitas',        5),
    ('AWOS_CAT3', 'WS',   'wind_speed_kt',   'numeric', 'kt',     'Wind speed',            'Kecepatan angin',            6),
    ('AWOS_CAT3', 'WD',   'wind_dir_deg',    'numeric', '°',      'Wind direction',        'Arah angin',                 7),
    ('AWOS_CAT3', 'WGS',  'gust_speed_kt',   'numeric', 'kt',     'Gust speed',            'Kecepatan hembusan',         8),
    ('AWOS_CAT3', 'WGD',  'gust_dir_deg',    'numeric', '°',      'Gust direction',        'Arah hembusan',              9),
    ('AWOS_CAT3', 'RVR',  'rvr_m',           'numeric', 'm',      'Runway visual range',   'Runway visual range',        10),
    ('AWOS_CAT3', 'VIS',  'vis_m',           'numeric', 'm',      'Visibility',            'Jarak pandang',              11),
    ('AWOS_CAT3', 'ALS',  'als_cd',          'numeric', 'cd',     'Ambient light',         'Cahaya latar',               12),
    ('AWOS_CAT3', 'D/N',  'als_dn',          'text',    NULL,     'Day / night',           'Siang / malam',              13),
    ('AWOS_CAT3', 'RLS',  'rls',             'numeric', NULL,     'Runway light setting',  'Pengaturan lampu landasan',  14),
    ('AWOS_CAT3', 'LR1',  'lr1_100ft',       'numeric', '100 ft', 'Cloud base (layer 1)',  'Dasar awan (lapisan 1)',     15),
    ('AWOS_CAT3', 'SKY',  'sky_condition',   'text',    NULL,     'Sky condition',         'Kondisi langit',             16),
    ('AWOS_CAT3', 'PW',   'present_weather', 'text',    NULL,     'Present weather',       'Cuaca saat ini',             17),
    ('AWOS_CAT3', 'RA',   'precip_mm',       'numeric', 'mm',     'Rainfall',              'Curah hujan',                18),
    ('AWOS_CAT3', 'SOL',  'solar_wm2',       'numeric', 'W/m²',   'Solar radiation',       'Radiasi matahari',           19),
    ('AWOS_CAT3', 'LTX',  'lightning',       'text',    NULL,     'Lightning',             'Petir',                      20);

-- Components per site (7 per site including DCP).
INSERT INTO component (site_id, type_code, sort)
SELECT st.id, v.type_code, ct.sort
FROM site st
JOIN system sy ON sy.id = st.system_id AND sy.code = 'WIDN-CAT3'
JOIN (VALUES
    ('RWY04', 'DCP'), ('RWY04', 'ATRH'), ('RWY04', 'BARO'), ('RWY04', 'ANEM'), ('RWY04', 'RVR'), ('RWY04', 'CEL'), ('RWY04', 'PWX'),
    ('RWYMID', 'DCP'), ('RWYMID', 'ATRH'), ('RWYMID', 'BARO'), ('RWYMID', 'ANEM'), ('RWYMID', 'RAIN'), ('RWYMID', 'SOLR'), ('RWYMID', 'LIGH'),
    ('RWY22', 'DCP'), ('RWY22', 'ATRH'), ('RWY22', 'BARO'), ('RWY22', 'ANEM'), ('RWY22', 'RVR'), ('RWY22', 'CEL'), ('RWY22', 'PWX')
) AS v(site_code, type_code) ON v.site_code = st.code
JOIN component_type ct ON ct.code = v.type_code;

INSERT INTO component_field (component_id, system_type_code, field_code)
SELECT c.id, 'AWOS_CAT3', v.field_code
FROM component c
JOIN site st ON st.id = c.site_id
JOIN (VALUES
    ('RWY04', 'ATRH', 'TEMP'), ('RWY04', 'ATRH', 'DEWP'), ('RWY04', 'ATRH', 'RH'),
    ('RWY04', 'BARO', 'QNH'), ('RWY04', 'BARO', 'DA'),
    ('RWY04', 'ANEM', 'WS'), ('RWY04', 'ANEM', 'WD'), ('RWY04', 'ANEM', 'WGS'), ('RWY04', 'ANEM', 'WGD'),
    ('RWY04', 'RVR', 'RVR'), ('RWY04', 'RVR', 'VIS'), ('RWY04', 'RVR', 'ALS'), ('RWY04', 'RVR', 'D/N'), ('RWY04', 'RVR', 'RLS'),
    ('RWY04', 'CEL', 'LR1'), ('RWY04', 'CEL', 'SKY'),
    ('RWY04', 'PWX', 'PW'), ('RWY04', 'PWX', 'RA'),
    ('RWYMID', 'ATRH', 'TEMP'), ('RWYMID', 'ATRH', 'DEWP'), ('RWYMID', 'ATRH', 'RH'),
    ('RWYMID', 'BARO', 'QNH'), ('RWYMID', 'BARO', 'DA'),
    ('RWYMID', 'ANEM', 'WS'), ('RWYMID', 'ANEM', 'WD'), ('RWYMID', 'ANEM', 'WGS'), ('RWYMID', 'ANEM', 'WGD'),
    ('RWYMID', 'RAIN', 'RA'), ('RWYMID', 'SOLR', 'SOL'), ('RWYMID', 'LIGH', 'LTX'),
    ('RWY22', 'ATRH', 'TEMP'), ('RWY22', 'ATRH', 'DEWP'), ('RWY22', 'ATRH', 'RH'),
    ('RWY22', 'BARO', 'QNH'), ('RWY22', 'BARO', 'DA'),
    ('RWY22', 'ANEM', 'WS'), ('RWY22', 'ANEM', 'WD'), ('RWY22', 'ANEM', 'WGS'), ('RWY22', 'ANEM', 'WGD'),
    ('RWY22', 'RVR', 'RVR'), ('RWY22', 'RVR', 'VIS'), ('RWY22', 'RVR', 'RLS'),
    ('RWY22', 'CEL', 'LR1'), ('RWY22', 'CEL', 'SKY'),
    ('RWY22', 'PWX', 'PW'), ('RWY22', 'PWX', 'RA')
) AS v(site_code, type_code, field_code) ON v.site_code = st.code AND v.type_code = c.type_code;

-- Default mandatory fields (decision B4a).
INSERT INTO mandatory_field (system_type_code, component_type_code, field_code) VALUES
    ('AWOS_CAT3', 'ATRH', 'TEMP'), ('AWOS_CAT3', 'ATRH', 'RH'),
    ('AWOS_CAT3', 'BARO', 'QNH'),
    ('AWOS_CAT3', 'ANEM', 'WS'), ('AWOS_CAT3', 'ANEM', 'WD'),
    ('AWOS_CAT3', 'RVR', 'RVR'),
    ('AWOS_CAT3', 'CEL', 'LR1'),
    ('AWOS_CAT3', 'PWX', 'PW'),
    ('AWOS_CAT3', 'RAIN', 'RA'),
    ('AWOS_CAT3', 'SOLR', 'SOL'),
    ('AWOS_CAT3', 'LIGH', 'LTX');

-- Default settings (FR-ADM-003, FR-DSH-010/012, FR-KPI-003).
INSERT INTO setting (key, value) VALUES
    ('grace_minutes', '3'),
    ('color_thresholds', '{"good": 99, "warning": 95}'),
    ('problem_thresholds', '{"cdp_no_data_min": 2, "cdp_unreachable_min": 2, "site_no_data_min": 2, "field_missing_min": 5, "ingest_lag_min": 5, "backup_overdue_h": 26}');
