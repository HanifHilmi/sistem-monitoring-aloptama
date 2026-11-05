-- R2.4.1: saving a rule's new version, or turning it off, withdraws the undecided suspects of its older versions
-- (decided ones keep their version). One-time cleanup of the suspects older versions left before this change.
DELETE FROM dq_detection d
WHERE d.status = 'suspect'
  AND d.rule_version < (SELECT max(v.version) FROM dq_rule_version v WHERE v.rule_id = d.rule_id);
