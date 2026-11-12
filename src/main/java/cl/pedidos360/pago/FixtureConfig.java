package cl.pedidos360.pago;

import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration
public class FixtureConfig {
    @Bean
    @ConditionalOnProperty(name = "pago.fixtures.enabled", havingValue = "true")
    ApplicationRunner fixtures(JdbcTemplate jdbc, TransactionTemplate tx,
                              @Value("${pago.security.tenant}") UUID tenant) {
        return args -> tx.executeWithoutResult(status -> {
            jdbc.update("INSERT INTO simulation_instrument VALUES ('sim-approved','APPROVED'), ('sim-declined','DECLINED') ON CONFLICT DO NOTHING");
            jdbc.update("INSERT INTO card_guard SELECT id FROM simulation_instrument ON CONFLICT DO NOTHING");
            // Two explicitly synthetic owners, never an identity supplied by a browser.
            for (int owner = 1; owner <= 2; owner++) {
                UUID oid = UUID.fromString("00000000-0000-4000-8000-00000000000" + owner);
                for (int n = 1; n <= 12; n++) {
                    UUID operation = UUID.fromString("10000000-0000-4000-800" + owner + "-" + String.format("%012d", n));
                    jdbc.update("""
                            INSERT INTO fixture_operation VALUES (?,?,?,?, 'CLP', clock_timestamp() + interval '7 days')
                            ON CONFLICT DO NOTHING
                            """, operation, tenant, oid, new java.math.BigDecimal("12990.00"));
                }
            }
        });
    }
}
