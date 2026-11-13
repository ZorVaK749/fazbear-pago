package cl.pedidos360.pago;

import java.util.concurrent.TimeUnit;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration
@EnableScheduling
@ConditionalOnProperty(name = "pago.kafka.enabled", havingValue = "true")
public class OutboxPublisher {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final KafkaTemplate<String, String> kafka;

    OutboxPublisher(JdbcTemplate jdbc, TransactionTemplate tx, KafkaTemplate<String, String> kafka) {
        this.jdbc = jdbc; this.tx = tx; this.kafka = kafka;
    }

    @Scheduled(fixedDelayString = "${pago.kafka.poll-ms:1000}")
    public void publish() {
        for (int i = 0; i < 5; i++) {
            Boolean found = tx.execute(s -> {
                var rows = jdbc.queryForList("""
                        SELECT * FROM payment_outbox WHERE published_at IS NULL AND next_attempt_at <= clock_timestamp()
                        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                        """);
                if (rows.isEmpty()) return false;
                var row = rows.getFirst();
                try {
                    kafka.send((String) row.get("event_type"), row.get("payment_id").toString(), (String) row.get("payload"))
                            .get(5, TimeUnit.SECONDS);
                    jdbc.update("UPDATE payment_outbox SET published_at=clock_timestamp(),attempts=attempts+1 WHERE event_id=?", row.get("event_id"));
                } catch (Exception e) {
                    if (e instanceof InterruptedException) Thread.currentThread().interrupt();
                    jdbc.update("UPDATE payment_outbox SET attempts=attempts+1,next_attempt_at=clock_timestamp()+interval '5 seconds' WHERE event_id=?", row.get("event_id"));
                }
                return true;
            });
            if (!Boolean.TRUE.equals(found)) break;
        }
    }
}
