package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

@Service
@ConditionalOnProperty(name = "pago.webpay.enabled", havingValue = "true")
class WebpayService {
    private static final Logger log = LoggerFactory.getLogger(WebpayService.class);
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final WebpayClient provider;
    private final PaymentService payments;

    WebpayService(JdbcTemplate db, TransactionTemplate tx, WebpayClient provider, PaymentService payments) {
        this.db = db;
        this.tx = tx;
        this.provider = provider;
        this.payments = payments;
    }

    record Redirect(UUID pagoId, String url, String token) {
        @Override public String toString() { return "Webpay redirect"; }
    }
    record Return(String tokenWs, String tbkToken, String buyOrder, String sessionId) {
        @Override public String toString() { return "Webpay return"; }
    }
    private record Reservation(UUID payment, String order, String session, int amount, boolean created) {}
    private record MatchedReturn(UUID payment, boolean firstNormalReturn) {}
    private enum Confirmation { DIRECT, RESUME, STATUS_ONLY }

    Redirect start(Owner owner, UUID operation, String key) {
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) throw new ApiException(400, "INVALID_IDEMPOTENCY_KEY");
        Reservation reservation = tx.execute(status -> reserve(owner, operation, key));
        if (reservation.created()) {
            WebpayClient.Created created;
            try {
                created = provider.create(reservation.order(), reservation.session(), reservation.amount());
            } catch (RestClientException unavailable) {
                createUnknown(reservation.payment());
                throw new ApiException(503, "WEBPAY_CREATE_UNKNOWN");
            }
            if (created == null || !WebpayClient.FORM.equals(created.url()) || !validToken(created.token())) {
                createUnknown(reservation.payment());
                throw new ApiException(502, "INVALID_WEBPAY_CREATE");
            }
            tx.executeWithoutResult(status -> {
                db.update("UPDATE webpay_transaction SET provider_token=? WHERE payment_id=?", created.token(), reservation.payment());
                db.update("UPDATE payment SET status='PENDING' WHERE id=?", reservation.payment());
            });
        }
        var saved = db.queryForMap("""
                SELECT p.status, w.provider_token FROM payment p JOIN webpay_transaction w ON w.payment_id=p.id
                WHERE p.id=?
                """, reservation.payment());
        if (!"PENDING".equals(saved.get("status"))) throw new ApiException(409, "WEBPAY_REDIRECT_UNAVAILABLE");
        return new Redirect(reservation.payment(), WebpayClient.FORM, (String) saved.get("provider_token"));
    }

    private Reservation reserve(Owner owner, UUID operation, String key) {
        db.execute("SET LOCAL lock_timeout = '5s'");
        String hash = fingerprint(operation);
        db.update("INSERT INTO idempotency_record(tenant_id,owner_id,key,request_hash) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                owner.tenant(), owner.oid(), key, hash);
        var existing = db.queryForMap("""
                SELECT request_hash,payment_id FROM idempotency_record
                WHERE tenant_id=? AND owner_id=? AND key=? FOR UPDATE
                """, owner.tenant(), owner.oid(), key);
        if (!hash.equals(existing.get("request_hash"))) throw new ApiException(409, "IDEMPOTENCY_CONFLICT");
        if (existing.get("payment_id") instanceof UUID id) return new Reservation(id, null, null, 0, false);
        var quote = db.queryForList("""
                SELECT amount,currency,expires_at FROM fixture_operation
                WHERE id=? AND tenant_id=? AND owner_id=? FOR UPDATE
                """, operation, owner.tenant(), owner.oid());
        if (quote.isEmpty()) throw new ApiException(404, "OPERATION_NOT_FOUND");
        var trusted = quote.getFirst();
        if (!db.queryForObject("SELECT clock_timestamp() < ?", Boolean.class, (Timestamp) trusted.get("expires_at")))
            throw new ApiException(409, "OPERATION_EXPIRED");
        if (Boolean.TRUE.equals(db.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM payment WHERE operation_id=?
                AND (NOT simulation OR status IN ('APPROVED','REFUNDED')))
                """, Boolean.class, operation))) throw new ApiException(409, "OPERATION_ALREADY_USED");
        int amount;
        try {
            amount = ((BigDecimal) trusted.get("amount")).intValueExact();
        } catch (ArithmeticException e) {
            throw new ApiException(422, "WEBPAY_REQUIRES_WHOLE_CLP");
        }
        UUID id = UUID.randomUUID();
        var order = id.toString().replace("-", "").substring(0, 26);
        var session = UUID.randomUUID().toString();
        db.update("""
                INSERT INTO payment(id,operation_id,tenant_id,owner_id,amount,currency,status,created_at,simulation)
                VALUES (?,?,?,?,?,?,'CREATING',clock_timestamp(),false)
                """, id, operation, owner.tenant(), owner.oid(), amount, trusted.get("currency"));
        db.update("INSERT INTO webpay_transaction(payment_id,operation_id,buy_order,session_id) VALUES (?,?,?,?)",
                id, operation, order, session);
        db.update("UPDATE idempotency_record SET payment_id=? WHERE tenant_id=? AND owner_id=? AND key=?",
                id, owner.tenant(), owner.oid(), key);
        return new Reservation(id, order, session, amount, true);
    }

    Payment finish(Owner owner, Return returned) {
        if (returned == null || (returned.tokenWs() != null && returned.tbkToken() != null))
            throw new ApiException(400, "INVALID_WEBPAY_RETURN");
        String token = returned.tokenWs() != null ? returned.tokenWs() : returned.tbkToken();
        if (token != null ? !validToken(token) : !validReturnReference(returned))
            throw new ApiException(400, "INVALID_WEBPAY_RETURN");
        // Persist the authenticated browser return before calling the provider. A failed HTTP
        // exchange must not erase the evidence needed to resume by the public payment ID.
        MatchedReturn matched = tx.execute(status -> {
            db.execute("SET LOCAL lock_timeout = '5s'");
            String query = """
                    SELECT p.id,p.status,w.browser_return_received
                    FROM payment p JOIN webpay_transaction w ON w.payment_id=p.id
                    WHERE p.tenant_id=? AND p.owner_id=? AND
                    """;
            var rows = token == null
                    ? db.queryForList(query + "w.buy_order=? AND w.session_id=? FOR UPDATE OF p",
                            owner.tenant(), owner.oid(), returned.buyOrder(), returned.sessionId())
                    : db.queryForList(query + "w.provider_token=? FOR UPDATE OF p", owner.tenant(), owner.oid(), token);
            if (rows.isEmpty()) throw new ApiException(404, "PAYMENT_NOT_FOUND");
            var saved = rows.getFirst();
            UUID id = (UUID) saved.get("id");
            boolean first = returned.tokenWs() != null && "PENDING".equals(saved.get("status"))
                    && !Boolean.TRUE.equals(saved.get("browser_return_received"));
            if (first) db.update("UPDATE webpay_transaction SET browser_return_received=true WHERE payment_id=?", id);
            return new MatchedReturn(id, first);
        });
        Confirmation mode = matched.firstNormalReturn() ? Confirmation.DIRECT
                : returned.tokenWs() != null ? Confirmation.RESUME : Confirmation.STATUS_ONLY;
        return reconcile(owner, matched.payment(), mode);
    }

    Payment recover(Owner owner, UUID id) {
        return reconcile(owner, id, Confirmation.RESUME);
    }

    private Payment reconcile(Owner owner, UUID id, Confirmation mode) {
        return tx.execute(status -> {
            db.execute("SET LOCAL lock_timeout = '5s'");
            var rows = db.queryForList("""
                    SELECT p.status,p.amount,w.buy_order,w.session_id,w.provider_token,w.browser_return_received,
                           p.created_at < clock_timestamp() - interval '30 minutes' AS past_integration_window
                    FROM payment p JOIN webpay_transaction w ON w.payment_id=p.id
                    WHERE p.id=? AND p.tenant_id=? AND p.owner_id=? FOR UPDATE OF p
                    """, id, owner.tenant(), owner.oid());
            if (rows.isEmpty()) throw new ApiException(404, "PAYMENT_NOT_FOUND");
            var saved = rows.getFirst();
            if ("PENDING".equals(saved.get("status"))) {
                var result = resolve(saved, mode);
                if (!validOutcome(saved, result)) throw new ApiException(502, "WEBPAY_RESPONSE_MISMATCH");
                if ("AUTHORIZED".equals(result.status()) && Integer.valueOf(0).equals(result.responseCode())) {
                    db.update("UPDATE payment SET status='APPROVED' WHERE id=?", id);
                } else if ("REVERSED".equals(result.status()) || "NULLIFIED".equals(result.status())
                        || ("FAILED".equals(result.status()) && result.responseCode() != null && result.responseCode() != 0)) {
                    db.update("UPDATE payment SET status='DECLINED' WHERE id=?", id);
                } else if (mode == Confirmation.RESUME && "INITIALIZED".equals(result.status())
                        && result.responseCode() == null && Boolean.FALSE.equals(saved.get("browser_return_received"))
                        && Boolean.TRUE.equals(saved.get("past_integration_window"))) {
                    // The sandbox return window has elapsed. Record a local expiration, never a provider authorization.
                    db.update("UPDATE payment SET status='EXPIRED' WHERE id=?", id);
                }
            }
            return payments.get(owner, id);
        });
    }

    private WebpayClient.Outcome resolve(Map<String, Object> saved, Confirmation mode) {
        String token = (String) saved.get("provider_token");
        if (mode == Confirmation.DIRECT) return commitOrReadStatus(token);
        var current = readStatus(token);
        if (mode == Confirmation.RESUME && Boolean.TRUE.equals(saved.get("browser_return_received"))
                && validOutcome(saved, current) && "INITIALIZED".equals(current.status())) {
            return commitOrReadStatus(token);
        }
        return current;
    }

    private WebpayClient.Outcome commitOrReadStatus(String token) {
        try {
            var outcome = provider.commit(token);
            if (outcome != null) return outcome;
        } catch (RestClientException uncertain) {
            logFailure("commit", uncertain);
        }
        return readStatus(token);
    }

    private WebpayClient.Outcome readStatus(String token) {
        try {
            return provider.status(token);
        } catch (RestClientException e) {
            logFailure("status", e);
            throw new ApiException(503, "WEBPAY_STATUS_UNAVAILABLE");
        }
    }

    private static void logFailure(String operation, RestClientException exception) {
        // The provider URL can contain the token. Log only the operation and error category.
        log.warn("Webpay {} failed: {}", operation, exception instanceof RestClientResponseException response
                ? response.getStatusCode().value() : exception.getClass().getSimpleName());
    }

    static boolean validOutcome(Map<String, Object> saved, WebpayClient.Outcome result) {
        return result != null && saved.get("buy_order").equals(result.order())
                && saved.get("session_id").equals(result.session())
                && result.amount() != null && ((BigDecimal) saved.get("amount")).compareTo(result.amount()) == 0;
    }

    private void createUnknown(UUID id) {
        db.update("UPDATE payment SET status='CREATE_UNKNOWN' WHERE id=? AND status='CREATING'", id);
    }

    private static boolean validReturnReference(Return returned) {
        return returned.buyOrder() != null && returned.buyOrder().matches("[a-f0-9]{26}")
                && returned.sessionId() != null && returned.sessionId().matches("[a-f0-9-]{36}");
    }

    private static boolean validToken(String value) {
        return value != null && value.matches("[A-Za-z0-9]{20,128}");
    }

    private static String fingerprint(UUID operation) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(("webpay-v1\n" + operation).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
