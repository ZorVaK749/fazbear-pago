package cl.pedidos360.pago;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class PaymentEvents {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    PaymentEvents(JdbcTemplate jdbc, ObjectMapper mapper) { this.jdbc = jdbc; this.mapper = mapper; }

    void append(UUID paymentId, String type, Map<String, Object> extra) {
        var payment = jdbc.queryForMap("SELECT * FROM payment WHERE id=?", paymentId);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("pagoId", paymentId);
        data.put("operacionId", payment.get("operation_id"));
        data.put("tenantId", payment.get("tenant_id"));
        data.put("ownerId", payment.get("owner_id"));
        data.put("importe", payment.get("amount"));
        data.put("moneda", payment.get("currency"));
        data.put("simulacion", true);
        data.putAll(extra);
        UUID eventId = UUID.randomUUID();
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("eventId", eventId);
        envelope.put("eventType", type);
        envelope.put("schemaVersion", 1);
        envelope.put("occurredAt", Instant.now());
        envelope.put("producer", "ms-pago");
        envelope.put("aggregateId", paymentId.toString());
        envelope.put("aggregateVersion", type.equals("pago.reembolsado.v1") ? 2 : 1);
        envelope.put("correlationId", payment.get("operation_id"));
        envelope.put("data", data);
        try {
            jdbc.update("INSERT INTO payment_outbox(event_id,payment_id,event_type,payload) VALUES (?,?,?,?)",
                    eventId, paymentId, type, mapper.writeValueAsString(envelope));
        } catch (JsonProcessingException e) { throw new IllegalStateException("EVENT_SERIALIZATION_FAILED"); }
    }
}
