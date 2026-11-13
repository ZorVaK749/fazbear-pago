package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;
import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RefundService {
    private final JdbcTemplate jdbc;
    private final PaymentEvents events;
    RefundService(JdbcTemplate jdbc, PaymentEvents events) { this.jdbc = jdbc; this.events = events; }

    @Transactional
    public Map<String, Object> refund(Owner owner, UUID paymentId, String key) {
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) throw new ApiException(400, "INVALID_IDEMPOTENCY_KEY");
        var payments = jdbc.queryForList("SELECT * FROM payment WHERE id=? AND tenant_id=? AND owner_id=? FOR UPDATE",
                paymentId, owner.tenant(), owner.oid());
        if (payments.isEmpty()) throw new ApiException(404, "PAYMENT_NOT_FOUND");
        var existing = jdbc.queryForList("SELECT * FROM payment_refund WHERE payment_id=?", paymentId);
        if (!existing.isEmpty()) {
            var refund = existing.getFirst();
            if (!key.equals(refund.get("idempotency_key"))) throw new ApiException(409, "REFUND_ALREADY_COMPLETED");
            return Map.of("reembolsoId", refund.get("id"), "pagoId", paymentId, "importeReembolsado", refund.get("amount"), "simulacion", true);
        }
        var payment = payments.getFirst();
        if (!payment.get("status").equals("APPROVED")) throw new ApiException(409, "PAYMENT_NOT_APPROVED");
        UUID refundId = UUID.randomUUID();
        jdbc.update("INSERT INTO payment_refund(id,payment_id,idempotency_key,amount) VALUES (?,?,?,?)", refundId, paymentId, key, payment.get("amount"));
        jdbc.update("UPDATE payment SET status='REFUNDED' WHERE id=?", paymentId);
        events.append(paymentId, "pago.reembolsado.v1", Map.of("reembolsoId", refundId,
                "importeReembolsado", payment.get("amount"), "totalReembolsado", payment.get("amount")));
        return Map.of("reembolsoId", refundId, "pagoId", paymentId, "importeReembolsado", payment.get("amount"), "simulacion", true);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> trusted(UUID paymentId) {
        var rows = jdbc.queryForList("SELECT * FROM payment WHERE id=?", paymentId);
        if (rows.isEmpty()) throw new ApiException(404, "PAYMENT_NOT_FOUND");
        var p = rows.getFirst();
        BigDecimal refunded = jdbc.queryForObject("SELECT COALESCE(sum(amount),0) FROM payment_refund WHERE payment_id=?", BigDecimal.class, paymentId);
        return Map.of("pagoId", paymentId, "operacionId", p.get("operation_id"), "tenantId", p.get("tenant_id"),
                "ownerId", p.get("owner_id"), "importe", p.get("amount"), "moneda", p.get("currency"),
                "estado", p.get("status"), "simulacion", true, "totalReembolsado", refunded);
    }
}
