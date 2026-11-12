package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentService {
    // Inclusive window; database timestamptz precision is microseconds.
    static final String COUNT_WINDOW = """
            SELECT count(*) FROM payment_attempt
            WHERE instrument_id = ? AND attempted_at >= ? AND attempted_at <= ?
            """;
    private final JdbcTemplate jdbc;

    PaymentService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED, timeout = 15)
    public Result pay(Owner owner, String key, PaymentRequest request) {
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) {
            throw new ApiException(400, "INVALID_IDEMPOTENCY_KEY");
        }
        jdbc.execute("SET LOCAL lock_timeout = '5s'");
        jdbc.execute("SET LOCAL statement_timeout = '10s'");
        String hash = fingerprint(request);
        // ON CONFLICT waits for the first transaction; subsequent READ COMMITTED
        // statement observes its committed result. Failure rolls reservation back too.
        jdbc.update("""
                INSERT INTO idempotency_record(tenant_id, owner_id, key, request_hash)
                VALUES (?,?,?,?) ON CONFLICT DO NOTHING
                """, owner.tenant(), owner.oid(), key, hash);
        var record = jdbc.queryForMap("""
                SELECT request_hash, payment_id FROM idempotency_record
                WHERE tenant_id=? AND owner_id=? AND key=? FOR UPDATE
                """, owner.tenant(), owner.oid(), key);
        if (!hash.equals(record.get("request_hash"))) throw new ApiException(409, "IDEMPOTENCY_CONFLICT");
        if (record.get("payment_id") != null) {
            return new Result(get(owner, (UUID) record.get("payment_id")), true);
        }

        var operations = jdbc.queryForList("""
                SELECT amount, currency, expires_at FROM fixture_operation
                WHERE id=? AND tenant_id=? AND owner_id=? FOR UPDATE
                """, request.operacionId(), owner.tenant(), owner.oid());
        if (operations.isEmpty()) throw new ApiException(404, "OPERATION_NOT_FOUND");
        var operation = operations.getFirst();
        if (Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS(SELECT 1 FROM payment WHERE operation_id=? AND status='APPROVED')",
                Boolean.class, request.operacionId()))) {
            throw new ApiException(409, "OPERATION_ALREADY_APPROVED");
        }

        // Lock order is always idempotency -> operation -> global instrument.
        var guards = jdbc.queryForList("SELECT instrument_id FROM card_guard WHERE instrument_id=? FOR UPDATE",
                request.instrumentoPruebaId());
        if (guards.isEmpty()) throw new ApiException(400, "UNKNOWN_SIMULATION_INSTRUMENT");
        // clock_timestamp(), not transaction start or client time; read AFTER lock.
        OffsetDateTime now = jdbc.queryForObject("SELECT clock_timestamp()", OffsetDateTime.class);
        if (!now.toInstant().isBefore(((java.sql.Timestamp) operation.get("expires_at")).toInstant())) {
            throw new ApiException(409, "OPERATION_EXPIRED");
        }
        OffsetDateTime start = now.minusSeconds(10);
        long count = jdbc.queryForObject(COUNT_WINDOW, Long.class, request.instrumentoPruebaId(), start, now) + 1;
        boolean blocked = count > 3;
        String status = blocked ? "BLOCKED" : jdbc.queryForObject(
                "SELECT outcome FROM simulation_instrument WHERE id=?", String.class, request.instrumentoPruebaId());
        UUID paymentId = UUID.randomUUID();
        UUID attemptId = UUID.randomUUID();
        jdbc.update("""
                INSERT INTO payment(id, operation_id, tenant_id, owner_id, instrument_id, amount, currency, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """, paymentId, request.operacionId(), owner.tenant(), owner.oid(), request.instrumentoPruebaId(),
                operation.get("amount"), operation.get("currency"), status, now);
        jdbc.update("INSERT INTO payment_attempt VALUES (?,?,?,?)", attemptId, paymentId, request.instrumentoPruebaId(), now);
        jdbc.update("""
                INSERT INTO antifraud_decision VALUES (?,?,?,?,?, 'MORE_THAN_3_IN_10_SECONDS')
                """, attemptId, blocked, count, start, now);
        jdbc.update("""
                UPDATE idempotency_record SET payment_id=? WHERE tenant_id=? AND owner_id=? AND key=?
                """, paymentId, owner.tenant(), owner.oid(), key);
        return new Result(get(owner, paymentId), false);
    }

    @Transactional(readOnly = true)
    public Payment get(Owner owner, UUID id) {
        var rows = jdbc.query("SELECT * FROM payment WHERE id=? AND tenant_id=? AND owner_id=?",
                PaymentService::payment, id, owner.tenant(), owner.oid());
        if (rows.isEmpty()) throw new ApiException(404, "PAYMENT_NOT_FOUND");
        return rows.getFirst();
    }

    @Transactional(readOnly = true)
    public List<Payment> mine(Owner owner, int limit) {
        if (limit < 1 || limit > 100) throw new ApiException(400, "INVALID_LIMIT");
        return jdbc.query("""
                SELECT * FROM payment WHERE tenant_id=? AND owner_id=?
                ORDER BY created_at DESC, id LIMIT ?
                """, PaymentService::payment, owner.tenant(), owner.oid(), limit);
    }

    private static Payment payment(ResultSet rs, int row) throws SQLException {
        return new Payment(rs.getObject("id", UUID.class), rs.getObject("operation_id", UUID.class),
                rs.getString("status"), rs.getBigDecimal("amount"), rs.getString("currency"),
                rs.getBoolean("simulation"), rs.getObject("created_at", OffsetDateTime.class).toInstant());
    }

    private static String fingerprint(PaymentRequest request) {
        String canonical = "v1\n" + request.operacionId() + "\n" + request.metodo() + "\n" + request.instrumentoPruebaId();
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable");
        }
    }
}
