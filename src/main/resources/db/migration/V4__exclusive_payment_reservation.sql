-- Keep an active Webpay reservation exclusive even if an older writer still attempts a simulated approval.
CREATE UNIQUE INDEX one_live_payment_per_operation
    ON payment(operation_id)
    WHERE status IN ('CREATING','CREATE_UNKNOWN','PENDING','APPROVED','REFUNDED');
DROP INDEX one_approval_per_operation;
