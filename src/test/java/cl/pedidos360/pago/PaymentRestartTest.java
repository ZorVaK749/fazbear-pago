package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentIntegrationTest.*;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;

import java.time.Duration;
import java.util.UUID;
import cl.pedidos360.pago.PaymentModels.Payment;
import cl.pedidos360.pago.PaymentModels.PaymentRequest;
import org.junit.jupiter.api.Test;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.web.client.RestClient;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.containers.PostgreSQLContainer;
import com.github.dockerjava.api.model.ExposedPort;

class PaymentRestartTest {
    @Test
    void paymentAndIdempotencySurviveDatabaseAndApplicationRestart() throws Exception {
        // Brand-new container belonging ONLY to this test, never a Compose/R2 DB.
        try (var postgres = new PostgreSQLContainer<>("postgres:17.7-alpine")
                .withDatabaseName("restart_test").withUsername("synthetic").withPassword("synthetic-test-only")) {
            postgres.start();
            var request = new PaymentRequest(UUID.fromString("10000000-0000-4000-8001-000000000001"), "SIMULADO", "sim-approved");
            Payment first;
            try (var app = start(postgres, postgres.getJdbcUrl())) {
                first = pay(client(app), request);
                assertThat(first.estado()).isEqualTo("APPROVED");
                assertThat(app.getBean(org.springframework.jdbc.core.JdbcTemplate.class)
                        .queryForObject("SELECT count(*) FROM fixture_operation", Long.class)).isEqualTo(24);
            }

            DockerClientFactory.instance().client().restartContainerCmd(postgres.getContainerId()).exec();
            // Docker Desktop can allocate a NEW ephemeral host port on restart.
            // GenericContainer caches the original inspect/port mapping.
            var info = DockerClientFactory.instance().client().inspectContainerCmd(postgres.getContainerId()).exec();
            String hostPort = info.getNetworkSettings().getPorts().getBindings().get(ExposedPort.tcp(5432))[0].getHostPortSpec();
            String restartedUrl = "jdbc:postgresql://" + postgres.getHost() + ":" + hostPort + "/restart_test";
            await().atMost(Duration.ofSeconds(30)).ignoreExceptionsMatching(e -> e instanceof java.sql.SQLException).untilAsserted(() -> {
                try (var connection = java.sql.DriverManager.getConnection(restartedUrl, postgres.getUsername(), postgres.getPassword())) {
                    assertThat(connection.isValid(1)).isTrue();
                }
            });

            try (var app = start(postgres, restartedUrl)) {
                var client = client(app);
                Payment stored = client.get().uri("/api/pagos/" + first.pagoId())
                        .header("Authorization", "Bearer " + token(ALICE, b -> {})).retrieve().body(Payment.class);
                assertThat(stored).isEqualTo(first);
                assertThat(pay(client, request)).isEqualTo(first);
                var jdbc = app.getBean(org.springframework.jdbc.core.JdbcTemplate.class);
                for (String table : java.util.List.of("payment", "payment_attempt", "antifraud_decision", "idempotency_record")) {
                    assertThat(jdbc.queryForObject("SELECT count(*) FROM " + table, Long.class)).isEqualTo(1);
                }
                assertThat(jdbc.queryForObject("SELECT count(*) FROM fixture_operation", Long.class)).isEqualTo(24);
            }
        }
    }

    static ConfigurableApplicationContext start(PostgreSQLContainer<?> postgres, String url) {
        return new SpringApplicationBuilder(PagoApplication.class, Keys.class).run(
                "--server.port=0", "--spring.datasource.url=" + url,
                "--spring.datasource.username=" + postgres.getUsername(),
                "--spring.datasource.password=" + postgres.getPassword(),
                "--pago.fixtures.enabled=true", "--spring.main.banner-mode=off");
    }

    static RestClient client(ConfigurableApplicationContext app) {
        int port = ((ServletWebServerApplicationContext) app).getWebServer().getPort();
        return RestClient.create("http://127.0.0.1:" + port);
    }

    static Payment pay(RestClient client, PaymentRequest request) throws Exception {
        return client.post().uri("/api/pagos").header("Authorization", "Bearer " + token(ALICE, b -> {}))
                .header("Idempotency-Key", "survives-restart").contentType(MediaType.APPLICATION_JSON)
                .body(request).retrieve().body(Payment.class);
    }
}
