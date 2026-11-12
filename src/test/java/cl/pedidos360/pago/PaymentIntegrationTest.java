package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import java.math.BigDecimal;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.client.RestClient;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureMockMvc
@Testcontainers
@Import(PaymentIntegrationTest.Keys.class)
class PaymentIntegrationTest {
    static final String TENANT = "ee0d2c5b-e60b-4c57-9b30-8a38a520c430";
    static final String AUDIENCE = "304fa289-2b72-447b-9c48-f00998f7c22f";
    static final String ISSUER = "https://login.microsoftonline.com/" + TENANT + "/v2.0";
    static final Owner ALICE = new Owner(UUID.fromString(TENANT), UUID.fromString("00000000-0000-4000-8000-000000000001"));
    static final Owner BOB = new Owner(UUID.fromString(TENANT), UUID.fromString("00000000-0000-4000-8000-000000000002"));

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:17.7-alpine")
            .withDatabaseName("pago_test").withUsername("synthetic").withPassword("synthetic-test-only");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("pago.fixtures.enabled", () -> false);
    }

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @Autowired PaymentService service;
    @Autowired ObjectMapper json;
    @LocalServerPort int port;

    @BeforeEach
    void reset() {
        jdbc.execute("DROP TRIGGER IF EXISTS injected_failure ON antifraud_decision");
        jdbc.execute("DROP TRIGGER IF EXISTS injected_commit_failure ON payment");
        jdbc.execute("TRUNCATE idempotency_record, antifraud_decision, payment_attempt, payment, fixture_operation, card_guard, simulation_instrument CASCADE");
        jdbc.update("INSERT INTO simulation_instrument VALUES ('sim-approved','APPROVED'),('sim-declined','DECLINED')");
        jdbc.update("INSERT INTO card_guard SELECT id FROM simulation_instrument");
    }

    UUID operation(Owner owner) {
        UUID id = UUID.randomUUID();
        jdbc.update("INSERT INTO fixture_operation VALUES (?,?,?,?, 'CLP', clock_timestamp()+interval '1 hour')",
                id, owner.tenant(), owner.oid(), new BigDecimal("12990.00"));
        return id;
    }

    PaymentRequest request(Owner owner, String instrument) {
        return new PaymentRequest(operation(owner), "SIMULADO", instrument);
    }

    MvcResult postPayment(Owner owner, String key, PaymentRequest request) throws Exception {
        return mvc.perform(post("/api/pagos").header("Authorization", "Bearer " + token(owner, b -> {}))
                        .header("Idempotency-Key", key).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsBytes(request)))
                .andReturn();
    }

    Payment body(MvcResult result) throws Exception {
        return json.readValue(result.getResponse().getContentAsByteArray(), Payment.class);
    }

    long count(String table) { return jdbc.queryForObject("SELECT count(*) FROM " + table, Long.class); }

    @Test
    void approvedAmountIsBackendControlledAndPersisted() throws Exception {
        var result = postPayment(ALICE, "approved", request(ALICE, "sim-approved"));
        assertThat(result.getResponse().getStatus()).isEqualTo(201);
        Payment payment = body(result);
        assertThat(payment.estado()).isEqualTo("APPROVED");
        assertThat(payment.importe()).isEqualByComparingTo("12990.00");
        assertThat(payment.simulacion()).isTrue();
        for (String table : List.of("payment", "payment_attempt", "antifraud_decision", "idempotency_record")) {
            assertThat(count(table)).isEqualTo(1);
        }
        // Independent database connection, not an in-memory repository/session cache.
        try (var connection = java.sql.DriverManager.getConnection(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword());
             var statement = connection.createStatement(); var rows = statement.executeQuery("SELECT status FROM payment")) {
            assertThat(rows.next()).isTrue();
            assertThat(rows.getString(1)).isEqualTo("APPROVED");
        }
    }

    @Test
    void actualHttpServerRunsWithSignedJwtAndPostgres() throws Exception {
        var result = RestClient.create("http://127.0.0.1:" + port).post().uri("/api/pagos")
                .header("Authorization", "Bearer " + token(ALICE, b -> {})).header("Idempotency-Key", "socket-test")
                .contentType(MediaType.APPLICATION_JSON).body(request(ALICE, "sim-approved"))
                .retrieve().toEntity(Payment.class);
        assertThat(result.getStatusCode().value()).isEqualTo(201);
        assertThat(result.getBody().estado()).isEqualTo("APPROVED");
    }

    @Test
    void declinedPaymentIsStillAnAttempt() throws Exception {
        var result = postPayment(ALICE, "decline", request(ALICE, "sim-declined"));
        assertThat(result.getResponse().getStatus()).isEqualTo(201);
        assertThat(body(result).estado()).isEqualTo("DECLINED");
        assertThat(count("payment_attempt")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT blocked FROM antifraud_decision", Boolean.class)).isFalse();
    }

    @Test
    void fourthAttemptBlockedAcrossUsersNotClientId() throws Exception {
        for (int n = 1; n <= 4; n++) {
            Owner owner = n % 2 == 0 ? BOB : ALICE;
            var result = postPayment(owner, "attempt-" + n, request(owner, "sim-approved"));
            assertThat(result.getResponse().getStatus()).isEqualTo(n == 4 ? 429 : 201);
            assertThat(body(result).estado()).isEqualTo(n == 4 ? "BLOCKED" : "APPROVED");
        }
        assertThat(count("payment_attempt")).isEqualTo(4);
        assertThat(jdbc.queryForList("SELECT attempts_in_window FROM antifraud_decision ORDER BY decided_at", Long.class))
                .containsExactly(1L, 2L, 3L, 4L);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM antifraud_decision WHERE blocked", Long.class)).isEqualTo(1);
    }

    @Test
    void declinedAttemptsAlsoCountAndInstrumentsAreIndependent() throws Exception {
        for (int n = 1; n <= 4; n++) {
            var result = postPayment(ALICE, "declined-" + n, request(ALICE, "sim-declined"));
            assertThat(body(result).estado()).isEqualTo(n == 4 ? "BLOCKED" : "DECLINED");
        }
        assertThat(body(postPayment(ALICE, "other-instrument", request(ALICE, "sim-approved"))).estado()).isEqualTo("APPROVED");
    }

    @Test
    void slidingWindowExpiresWithoutThirtyMinuteHold() {
        for (int n = 0; n < 4; n++) service.pay(ALICE, "old-" + n, request(ALICE, "sim-approved"));
        jdbc.update("UPDATE payment_attempt SET attempted_at=clock_timestamp()-interval '10.1 seconds'");
        var next = service.pay(ALICE, "after-window", request(ALICE, "sim-approved"));
        assertThat(next.payment().estado()).isEqualTo("APPROVED");
        assertThat(jdbc.queryForObject("SELECT attempts_in_window FROM antifraud_decision ORDER BY decided_at DESC LIMIT 1", Long.class)).isEqualTo(1);
    }

    @Test
    void exactInclusiveWindowUsesMicrosecondBoundaries() {
        for (int n = 0; n < 4; n++) service.pay(ALICE, "boundary-" + n, request(ALICE, "sim-approved"));
        OffsetDateTime now = OffsetDateTime.ofInstant(Instant.parse("2026-11-12T12:00:10Z"), ZoneOffset.UTC);
        var ids = jdbc.queryForList("SELECT id FROM payment_attempt ORDER BY attempted_at", UUID.class);
        List<OffsetDateTime> times = List.of(now.minusSeconds(10).minusNanos(1000), now.minusSeconds(10), now, now.plusNanos(1000));
        for (int i = 0; i < 4; i++) jdbc.update("UPDATE payment_attempt SET attempted_at=? WHERE id=?", times.get(i), ids.get(i));
        assertThat(jdbc.queryForObject(PaymentService.COUNT_WINDOW, Long.class, "sim-approved", now.minusSeconds(10), now)).isEqualTo(2);
    }

    @Test
    void recentAttemptsWithinWindowBlock() {
        for (int n = 0; n < 3; n++) service.pay(ALICE, "recent-" + n, request(ALICE, "sim-approved"));
        jdbc.update("UPDATE payment_attempt SET attempted_at=clock_timestamp()-interval '9 seconds'");
        assertThat(service.pay(BOB, "recent-fourth", request(BOB, "sim-approved")).payment().estado()).isEqualTo("BLOCKED");
    }

    @Test
    void identicalReplayAddsNothingAndReturnsOriginal() throws Exception {
        var request = request(ALICE, "sim-approved");
        var first = postPayment(ALICE, "same", request);
        var replay = postPayment(ALICE, "same", request);
        assertThat(replay.getResponse().getStatus()).isEqualTo(200);
        assertThat(replay.getResponse().getHeader("Idempotency-Replayed")).isEqualTo("true");
        assertThat(body(replay)).isEqualTo(body(first));
        assertThat(count("payment_attempt")).isEqualTo(1);
    }

    @Test
    void blockedReplayAlsoAddsNothing() throws Exception {
        for (int n = 0; n < 3; n++) service.pay(ALICE, "prior-" + n, request(ALICE, "sim-approved"));
        var request = request(ALICE, "sim-approved");
        var first = postPayment(ALICE, "blocked", request);
        var second = postPayment(ALICE, "blocked", request);
        assertThat(second.getResponse().getStatus()).isEqualTo(429);
        assertThat(body(second)).isEqualTo(body(first));
        assertThat(count("payment_attempt")).isEqualTo(4);
    }

    @Test
    void changedContentForSameKeyConflicts() throws Exception {
        postPayment(ALICE, "conflict", request(ALICE, "sim-approved"));
        var changed = postPayment(ALICE, "conflict", request(ALICE, "sim-declined"));
        assertThat(changed.getResponse().getStatus()).isEqualTo(409);
        assertThat(count("payment_attempt")).isEqualTo(1);
    }

    @Test
    void keysAreNamespacedByValidatedOwner() {
        service.pay(ALICE, "shared-key", request(ALICE, "sim-approved"));
        service.pay(BOB, "shared-key", request(BOB, "sim-approved"));
        assertThat(count("idempotency_record")).isEqualTo(2);
    }

    @Test
    void noSecondApprovalForSameOperation() throws Exception {
        var request = request(ALICE, "sim-approved");
        postPayment(ALICE, "once", request);
        assertThat(postPayment(ALICE, "twice", request).getResponse().getStatus()).isEqualTo(409);
        assertThat(count("payment_attempt")).isEqualTo(1);
        assertThat(count("idempotency_record")).isEqualTo(1);
    }

    @Test
    void declinedOperationCanRetryWithDifferentInstrument() {
        UUID operation = operation(ALICE);
        service.pay(ALICE, "declined-op", new PaymentRequest(operation, "SIMULADO", "sim-declined"));
        var approved = service.pay(ALICE, "retry-op", new PaymentRequest(operation, "SIMULADO", "sim-approved"));
        assertThat(approved.payment().estado()).isEqualTo("APPROVED");
        assertThat(count("payment_attempt")).isEqualTo(2);
    }

    @Test
    void concurrentDistinctAttemptsSerializeGlobally() throws Exception {
        var requests = new ArrayList<Callable<Result>>();
        for (int n = 0; n < 12; n++) {
            Owner owner = n % 2 == 0 ? ALICE : BOB;
            var request = request(owner, "sim-approved");
            String key = "parallel-" + n;
            requests.add(() -> service.pay(owner, key, request));
        }
        var results = parallel(requests);
        assertThat(results.stream().filter(r -> r.payment().estado().equals("APPROVED")).count()).isEqualTo(3);
        assertThat(results.stream().filter(r -> r.payment().estado().equals("BLOCKED")).count()).isEqualTo(9);
        assertThat(count("payment_attempt")).isEqualTo(12);
        assertThat(jdbc.queryForList("SELECT attempts_in_window FROM antifraud_decision ORDER BY decided_at", Long.class))
                .containsExactly(1L, 2L, 3L, 4L, 5L, 6L, 7L, 8L, 9L, 10L, 11L, 12L);
    }

    @Test
    void concurrentSameKeyProducesExactlyOneAttempt() throws Exception {
        var request = request(ALICE, "sim-approved");
        var calls = new ArrayList<Callable<Result>>();
        for (int n = 0; n < 12; n++) calls.add(() -> service.pay(ALICE, "one-key", request));
        var results = parallel(calls);
        assertThat(results.stream().map(r -> r.payment().pagoId()).distinct().count()).isEqualTo(1);
        assertThat(results.stream().filter(r -> !r.replay()).count()).isEqualTo(1);
        assertThat(count("payment_attempt")).isEqualTo(1);
    }

    @Test
    void concurrentSameOperationDifferentKeysOnlyOneApproval() throws Exception {
        var request = request(ALICE, "sim-approved");
        var calls = new ArrayList<Callable<String>>();
        for (int n = 0; n < 8; n++) {
            String key = "same-op-" + n;
            calls.add(() -> {
                try { return service.pay(ALICE, key, request).payment().estado(); }
                catch (ApiException e) { return e.code; }
            });
        }
        assertThat(parallel(calls)).containsOnly("APPROVED", "OPERATION_ALREADY_APPROVED");
        assertThat(count("payment")).isEqualTo(1);
    }

    @Test
    void databaseTimestampIsTakenAfterWaitingForInstrumentLock() throws Exception {
        var request = request(ALICE, "sim-approved");
        try (var connection = java.sql.DriverManager.getConnection(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword());
             var executor = Executors.newSingleThreadExecutor()) {
            connection.setAutoCommit(false);
            try (var statement = connection.createStatement()) {
                statement.executeQuery("SELECT * FROM card_guard WHERE instrument_id='sim-approved' FOR UPDATE").close();
            }
            var result = executor.submit(() -> service.pay(ALICE, "wait-for-db-lock", request));
            org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(3)).until(() ->
                    jdbc.queryForObject("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%FROM card_guard%'", Long.class) > 0);
            OffsetDateTime releaseTime = jdbc.queryForObject("SELECT clock_timestamp()", OffsetDateTime.class);
            connection.commit();
            assertThat(result.get(10, TimeUnit.SECONDS).payment().creadoEn()).isAfterOrEqualTo(releaseTime.toInstant());
        }
    }

    @Test
    void databaseUniqueIndexRejectsSecondApprovalEvenOutsideService() {
        var paid = service.pay(ALICE, "unique-index", request(ALICE, "sim-approved"));
        assertThatThrownBy(() -> jdbc.update("""
                INSERT INTO payment SELECT ?, operation_id, tenant_id, owner_id, instrument_id,
                amount, currency, status, created_at, simulation FROM payment WHERE id=?
                """, UUID.randomUUID(), paid.payment().pagoId()))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(count("payment")).isEqualTo(1);
    }

    @Test
    void persistenceFailureRollsBackEverythingAndSameKeyCanRetry() throws Exception {
        jdbc.execute("""
                CREATE OR REPLACE FUNCTION fail_payment_fixture() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'synthetic persistence failure'; END $$
                """);
        jdbc.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON antifraud_decision FOR EACH ROW EXECUTE FUNCTION fail_payment_fixture()");
        var request = request(ALICE, "sim-approved");
        assertThat(postPayment(ALICE, "failed-write", request).getResponse().getStatus()).isEqualTo(503);
        for (String table : List.of("payment", "payment_attempt", "antifraud_decision", "idempotency_record")) assertThat(count(table)).isZero();
        jdbc.execute("DROP TRIGGER injected_failure ON antifraud_decision");
        assertThat(postPayment(ALICE, "failed-write", request).getResponse().getStatus()).isEqualTo(201);
        assertThat(count("payment_attempt")).isEqualTo(1);
    }

    @Test
    void deferredCommitFailureIsNotReportedAsApproval() throws Exception {
        jdbc.execute("""
                CREATE OR REPLACE FUNCTION fail_payment_fixture() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'synthetic commit failure'; END $$
                """);
        jdbc.execute("CREATE CONSTRAINT TRIGGER injected_commit_failure AFTER INSERT ON payment DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fail_payment_fixture()");
        var request = request(ALICE, "sim-approved");
        assertThat(postPayment(ALICE, "failed-commit", request).getResponse().getStatus()).isEqualTo(503);
        assertThat(count("payment_attempt")).isZero();
        assertThat(count("idempotency_record")).isZero();
        jdbc.execute("DROP TRIGGER injected_commit_failure ON payment");
        assertThat(postPayment(ALICE, "failed-commit", request).getResponse().getStatus()).isEqualTo(201);
    }

    @Test
    void foreignPaymentAndForeignOperationAreHidden() throws Exception {
        var request = request(ALICE, "sim-approved");
        Payment payment = body(postPayment(ALICE, "own", request));
        mvc.perform(get("/api/pagos/" + payment.pagoId()).header("Authorization", "Bearer " + token(BOB, b -> {})))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("PAYMENT_NOT_FOUND"));
        assertThat(postPayment(BOB, "foreign", request).getResponse().getStatus()).isEqualTo(404);
        mvc.perform(get("/api/pagos/me").header("Authorization", "Bearer " + token(BOB, b -> {})))
                .andExpect(status().isOk()).andExpect(content().json("[]"));
        mvc.perform(get("/api/pagos/" + payment.pagoId()).header("Authorization", "Bearer " + token(ALICE, b -> {})))
                .andExpect(status().isOk()).andExpect(jsonPath("$.pagoId").value(payment.pagoId().toString()));
    }

    @Test
    void expiredOperationAndUnknownInstrumentDoNotGenerateAttempts() throws Exception {
        var request = request(ALICE, "sim-approved");
        jdbc.update("UPDATE fixture_operation SET expires_at=clock_timestamp()-interval '1 second'");
        assertThat(postPayment(ALICE, "expired", request).getResponse().getStatus()).isEqualTo(409);
        assertThat(postPayment(ALICE, "unknown", request(ALICE, "sim-unknown")).getResponse().getStatus()).isEqualTo(400);
        assertThat(count("payment_attempt")).isZero();
        assertThat(count("idempotency_record")).isZero();
    }

    @Test
    void browserAmountsCardDataAndTimeAreRejected() throws Exception {
        var request = request(ALICE, "sim-approved");
        for (String extra : List.of("\"importe\":1", "\"pan\":\"synthetic-not-a-card\"", "\"cvv\":\"fake\"",
                "\"createdAt\":\"2026-01-01T00:00:00Z\"", "\"ownerId\":\"other\"")) {
            String body = json.writeValueAsString(request);
            body = body.substring(0, body.length() - 1) + "," + extra + "}";
            mvc.perform(post("/api/pagos").header("Authorization", "Bearer " + token(ALICE, b -> {}))
                            .header("Idempotency-Key", "untrusted").contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isBadRequest());
        }
        assertThat(count("payment_attempt")).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"tenant", "audience", "issuer", "expired", "future", "oid", "missing-oid", "missing-exp", "signature"})
    void invalidSignedJwtIsRejected(String kind) throws Exception {
        Consumer<JWTClaimsSet.Builder> change = b -> {
            switch (kind) {
                case "tenant" -> b.claim("tid", UUID.randomUUID().toString());
                case "audience" -> b.audience("wrong-api");
                case "issuer" -> b.issuer("https://example.invalid");
                case "expired" -> b.expirationTime(Date.from(Instant.now().minusSeconds(120)));
                case "future" -> b.notBeforeTime(Date.from(Instant.now().plusSeconds(120)));
                case "oid" -> b.claim("oid", "email-is-not-an-oid@example.invalid");
                case "missing-oid" -> b.claim("oid", null);
                case "missing-exp" -> b.expirationTime(null);
                default -> { }
            }
        };
        String token = token(ALICE, change);
        if (kind.equals("signature")) {
            String[] parts = token.split("\\.");
            byte[] sig = Base64.getUrlDecoder().decode(parts[2]);
            sig[0] ^= 1;
            token = parts[0] + "." + parts[1] + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(sig);
        }
        mvc.perform(get("/api/pagos/me").header("Authorization", "Bearer " + token)).andExpect(status().isUnauthorized());
        assertThat(count("payment_attempt")).isZero();
    }

    @Test
    void noJwtAndAppOnlyWithoutDelegatedScopeFailClosed() throws Exception {
        mvc.perform(get("/api/pagos/me")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/pagos/me").header("Authorization", "Bearer not-a-jwt")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/pagos/me").header("Authorization", "Bearer " + token(ALICE, b -> b.claim("scp", null).claim("roles", List.of("Admin")))))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/pagos/me").header("Authorization", "Bearer " + token(ALICE, b -> b.claim("scp", "other_scope"))))
                .andExpect(status().isForbidden());
    }

    @Test
    void missingKeyAndUnboundedQueriesRejected() throws Exception {
        mvc.perform(post("/api/pagos").header("Authorization", "Bearer " + token(ALICE, b -> {}))
                        .contentType(MediaType.APPLICATION_JSON).content(json.writeValueAsBytes(request(ALICE, "sim-approved"))))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/pagos/me?limit=101").header("Authorization", "Bearer " + token(ALICE, b -> {})))
                .andExpect(status().isBadRequest());
    }

    static <T> List<T> parallel(List<Callable<T>> calls) throws Exception {
        try (var executor = Executors.newFixedThreadPool(calls.size())) {
            var ready = new CountDownLatch(calls.size());
            var go = new CountDownLatch(1);
            var futures = calls.stream().map(call -> executor.submit(() -> {
                ready.countDown();
                if (!go.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("test barrier timeout");
                return call.call();
            })).toList();
            assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue();
            go.countDown();
            var results = new ArrayList<T>();
            for (var future : futures) results.add(future.get(20, TimeUnit.SECONDS));
            return results;
        }
    }

    static String token(Owner owner, Consumer<JWTClaimsSet.Builder> change) throws Exception {
        var builder = new JWTClaimsSet.Builder().issuer(ISSUER).audience(AUDIENCE).subject("sub-is-not-oid")
                .claim("tid", owner.tenant().toString()).claim("oid", owner.oid().toString()).claim("scp", "access_as_user")
                .expirationTime(Date.from(Instant.now().plusSeconds(300))).notBeforeTime(Date.from(Instant.now().minusSeconds(5)));
        change.accept(builder);
        var jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.RS256), builder.build());
        jwt.sign(new RSASSASigner(Keys.PRIVATE));
        return jwt.serialize();
    }

    @TestConfiguration
    static class Keys {
        static final RSAPublicKey PUBLIC;
        static final RSAPrivateKey PRIVATE;
        static {
            try {
                var generator = KeyPairGenerator.getInstance("RSA");
                generator.initialize(2048);
                var pair = generator.generateKeyPair();
                PUBLIC = (RSAPublicKey) pair.getPublic();
                PRIVATE = (RSAPrivateKey) pair.getPrivate();
            } catch (Exception e) { throw new ExceptionInInitializerError(e); }
        }

        @Bean @Primary
        JwtDecoder testDecoder() {
            var decoder = NimbusJwtDecoder.withPublicKey(PUBLIC).build();
            decoder.setJwtValidator(SecurityConfig.validators(TENANT, AUDIENCE));
            return decoder;
        }
    }
}
