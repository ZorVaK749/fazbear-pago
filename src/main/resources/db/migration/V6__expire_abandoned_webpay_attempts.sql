ALTER TABLE payment DROP CONSTRAINT payment_method_status_check;
ALTER TABLE payment ADD CONSTRAINT payment_method_status_check CHECK (
    (simulation AND instrument_id IS NOT NULL AND status IN ('APPROVED','DECLINED','BLOCKED','REFUNDED'))
    OR (NOT simulation AND instrument_id IS NULL AND status IN ('CREATING','CREATE_UNKNOWN','PENDING','APPROVED','DECLINED','EXPIRED'))
);
