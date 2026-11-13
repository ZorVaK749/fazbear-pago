package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.HttpClientErrorException;

@Service
public class QuoteImportService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final RestClient orden;
    private final boolean enabled;

    QuoteImportService(JdbcTemplate jdbc, TransactionTemplate tx,
                       @Value("${pago.operations.remote-enabled:false}") boolean enabled,
                       @Value("${pago.operations.orden-url:http://localhost:8084}") String url) {
        this.jdbc = jdbc;
        this.tx = tx;
        this.enabled = enabled;
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(5000);
        this.orden = RestClient.builder().baseUrl(url).requestFactory(factory).build();
    }

    public void ensure(Owner owner, UUID id, String bearer) {
        if (!enabled) return;
        if (Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM fixture_operation WHERE id=? AND tenant_id=? AND owner_id=?)",
                Boolean.class, id, owner.tenant(), owner.oid()))) return;
        Quote quote;
        try {
            quote = orden.get().uri("/api/orden/cotizaciones/{id}", id)
                    .header("Authorization", bearer).retrieve().body(Quote.class);
        } catch (HttpClientErrorException e) {
            if (e.getStatusCode().value() == 404) throw new ApiException(404, "OPERATION_NOT_FOUND");
            throw new ApiException(503, "QUOTE_VERIFICATION_UNAVAILABLE");
        } catch (RuntimeException e) {
            throw new ApiException(503, "QUOTE_VERIFICATION_UNAVAILABLE");
        }
        if (quote == null || !id.equals(quote.operacionId()) || !owner.tenant().equals(quote.tenantId())
                || !owner.oid().equals(quote.ownerId()) || quote.importe() == null || quote.importe().signum() <= 0
                || quote.importe().scale() > 2 || quote.importe().precision() > 19
                || !"CLP".equals(quote.moneda()) || quote.expiraEn() == null) {
            throw new ApiException(502, "INVALID_TRUSTED_QUOTE");
        }
        tx.executeWithoutResult(s -> jdbc.update("""
                INSERT INTO fixture_operation VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING
                """, id, owner.tenant(), owner.oid(), quote.importe(), quote.moneda(), quote.expiraEn()));
    }

    @com.fasterxml.jackson.annotation.JsonIgnoreProperties(ignoreUnknown = true)
    public record Quote(UUID operacionId, UUID tenantId, UUID ownerId, BigDecimal importe, String moneda, OffsetDateTime expiraEn) {}
}
