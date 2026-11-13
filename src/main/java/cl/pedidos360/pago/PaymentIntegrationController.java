package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

@RestController
public class PaymentIntegrationController {
    private final RefundService refunds;
    private final PaymentService payments;
    private final JdbcTemplate jdbc;
    PaymentIntegrationController(RefundService refunds, PaymentService payments, JdbcTemplate jdbc) {
        this.refunds = refunds; this.payments = payments; this.jdbc = jdbc;
    }

    @GetMapping("/internal/pagos/{id}")
    Map<String, Object> trusted(@PathVariable UUID id) { return refunds.trusted(id); }

    @PostMapping("/api/pagos/{id}/anulacion")
    Map<String, Object> refund(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID id,
                               @RequestHeader(value = "Idempotency-Key", required = false) String key) {
        return refunds.refund(Owner.from(jwt), id, key);
    }

    @GetMapping("/api/pagos/{id}/intentos")
    List<Map<String, Object>> attempts(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        payments.get(Owner.from(jwt), id);
        return jdbc.queryForList("""
                SELECT a.id,a.attempted_at,d.blocked,d.attempts_in_window,d.rule
                FROM payment_attempt a JOIN antifraud_decision d ON d.attempt_id=a.id WHERE a.payment_id=?
                """, id);
    }

    @GetMapping("/api/pagos/me/alertas")
    List<Map<String, Object>> alerts(@AuthenticationPrincipal Jwt jwt) {
        Owner owner = Owner.from(jwt);
        return jdbc.queryForList("""
                SELECT f.payment_id,f.rule,f.created_at FROM fraud_alert f JOIN payment p ON p.id=f.payment_id
                WHERE p.tenant_id=? AND p.owner_id=? ORDER BY f.created_at DESC LIMIT 100
                """, owner.tenant(), owner.oid());
    }
}
