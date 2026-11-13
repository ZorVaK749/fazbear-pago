ALTER TABLE payment DROP CONSTRAINT payment_status_check;
ALTER TABLE payment ADD CONSTRAINT payment_status_check CHECK (status IN ('APPROVED','DECLINED','BLOCKED','REFUNDED'));
DROP INDEX one_approval_per_operation;
CREATE UNIQUE INDEX one_approval_per_operation ON payment(operation_id) WHERE status IN ('APPROVED','REFUNDED');
CREATE TABLE payment_refund (
    id uuid PRIMARY KEY,
    payment_id uuid NOT NULL UNIQUE REFERENCES payment(id),
    idempotency_key varchar(128) NOT NULL,
    amount numeric(19,2) NOT NULL CHECK (amount > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE fraud_alert (
    payment_id uuid PRIMARY KEY REFERENCES payment(id),
    attempt_id uuid NOT NULL UNIQUE REFERENCES payment_attempt(id),
    rule varchar(64) NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE payment_outbox (
    event_id uuid PRIMARY KEY,
    payment_id uuid NOT NULL REFERENCES payment(id),
    event_type varchar(64) NOT NULL,
    payload text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX pending_payment_outbox ON payment_outbox(next_attempt_at) WHERE published_at IS NULL;
-- Instruments are a simulator contract, not operation fixtures or real card tokens.
INSERT INTO simulation_instrument VALUES ('sim-approved','APPROVED'),('sim-declined','DECLINED') ON CONFLICT DO NOTHING;
INSERT INTO card_guard SELECT id FROM simulation_instrument ON CONFLICT DO NOTHING;
