ALTER TABLE payment ALTER COLUMN instrument_id DROP NOT NULL;
ALTER TABLE payment DROP CONSTRAINT payment_simulation_check;
ALTER TABLE payment DROP CONSTRAINT payment_status_check;
ALTER TABLE payment ADD CONSTRAINT payment_method_status_check CHECK (
    (simulation AND instrument_id IS NOT NULL AND status IN ('APPROVED','DECLINED','BLOCKED','REFUNDED'))
    OR (NOT simulation AND instrument_id IS NULL AND status IN ('CREATING','CREATE_UNKNOWN','PENDING','APPROVED','DECLINED'))
);
CREATE TABLE webpay_transaction (
    payment_id uuid PRIMARY KEY REFERENCES payment(id),
    operation_id uuid NOT NULL UNIQUE REFERENCES fixture_operation(id),
    buy_order varchar(26) NOT NULL UNIQUE,
    session_id varchar(61) NOT NULL,
    provider_token varchar(128) UNIQUE
);
