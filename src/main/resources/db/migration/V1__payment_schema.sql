-- Only synthetic instrument identifiers are accepted. No banking credentials.
CREATE TABLE simulation_instrument (
    id varchar(64) PRIMARY KEY CHECK (id LIKE 'sim-%'),
    outcome varchar(16) NOT NULL CHECK (outcome IN ('APPROVED', 'DECLINED'))
);
-- This row is the global serialization point, shared across owners/instances.
CREATE TABLE card_guard (
    instrument_id varchar(64) PRIMARY KEY REFERENCES simulation_instrument(id)
);
CREATE TABLE fixture_operation (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    amount numeric(19,2) NOT NULL CHECK (amount > 0),
    currency varchar(3) NOT NULL CHECK (currency = 'CLP'),
    expires_at timestamptz NOT NULL
);
CREATE TABLE payment (
    id uuid PRIMARY KEY,
    operation_id uuid NOT NULL REFERENCES fixture_operation(id),
    tenant_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    instrument_id varchar(64) NOT NULL REFERENCES simulation_instrument(id),
    amount numeric(19,2) NOT NULL CHECK (amount > 0),
    currency varchar(3) NOT NULL CHECK (currency = 'CLP'),
    status varchar(16) NOT NULL CHECK (status IN ('APPROVED', 'DECLINED', 'BLOCKED')),
    created_at timestamptz NOT NULL,
    simulation boolean NOT NULL DEFAULT true CHECK (simulation)
);
CREATE UNIQUE INDEX one_approval_per_operation ON payment(operation_id) WHERE status = 'APPROVED';
CREATE INDEX own_payments ON payment(tenant_id, owner_id, created_at DESC, id);
CREATE TABLE payment_attempt (
    id uuid PRIMARY KEY,
    payment_id uuid NOT NULL UNIQUE REFERENCES payment(id),
    instrument_id varchar(64) NOT NULL REFERENCES simulation_instrument(id),
    attempted_at timestamptz NOT NULL
);
CREATE INDEX instrument_window ON payment_attempt(instrument_id, attempted_at);
CREATE TABLE antifraud_decision (
    attempt_id uuid PRIMARY KEY REFERENCES payment_attempt(id),
    blocked boolean NOT NULL,
    attempts_in_window bigint NOT NULL CHECK (attempts_in_window > 0),
    window_start timestamptz NOT NULL,
    decided_at timestamptz NOT NULL,
    rule varchar(64) NOT NULL CHECK (rule = 'MORE_THAN_3_IN_10_SECONDS'),
    CHECK (blocked = (attempts_in_window > 3))
);
CREATE TABLE idempotency_record (
    tenant_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    key varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    payment_id uuid UNIQUE REFERENCES payment(id),
    PRIMARY KEY (tenant_id, owner_id, key)
);
