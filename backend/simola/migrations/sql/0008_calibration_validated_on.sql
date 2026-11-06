-- R2.5.1: when a calibration's certificate was validated (document validation). Empty means the calibration was
-- done but its certificate is still pending. The next due date still counts from the calibration date.
ALTER TABLE calibration_record
    ADD COLUMN validated_on date,
    ADD CONSTRAINT calibration_validated_after_date CHECK (validated_on IS NULL OR validated_on >= date);
