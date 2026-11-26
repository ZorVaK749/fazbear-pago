ALTER TABLE payment DROP CONSTRAINT payment_method_status_check;
ALTER TABLE payment ADD CONSTRAINT payment_method_status_check CHECK (
    (simulation AND instrument_id IS NOT NULL AND status IN ('APPROVED','DECLINED','BLOCKED','REFUNDED'))
    OR (NOT simulation AND instrument_id IS NULL AND status IN
        ('CREATING','CREATE_UNKNOWN','PENDING','APPROVED','DECLINED','EXPIRED','BLOCKED'))
);

CREATE TABLE webpay_start_decision (
    payment_id uuid PRIMARY KEY REFERENCES payment(id) ON DELETE CASCADE,
    attempts_in_window bigint NOT NULL CHECK (attempts_in_window > 0),
    blocked boolean NOT NULL,
    CHECK (blocked = (attempts_in_window > 3))
);
