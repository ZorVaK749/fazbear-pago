package cl.pedidos360.pago;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;

class AwsSafetyTest {
    MockEnvironment safe() { var e = new MockEnvironment().withProperty("spring.datasource.url", "jdbc:postgresql://db.invalid/test")
        .withProperty("INTERNAL_SERVICE_KEY", "synthetic-test-only-service-key-32")
        .withProperty("pago.operations.remote-enabled", "true").withProperty("pago.kafka.enabled", "true");
        e.setActiveProfiles("ev3-aws"); return e; }
    @Test void permitsAwsWithoutLabIdentity() { assertDoesNotThrow(() -> new AwsSafety(safe()).afterPropertiesSet()); }
    @ParameterizedTest @ValueSource(strings={"local", "ev3-local", "test"})
    void rejectsMixedProfiles(String p) { var e=safe(); e.setActiveProfiles("ev3-aws",p);
        assertThrows(IllegalStateException.class, () -> new AwsSafety(e).afterPropertiesSet()); }
    @ParameterizedTest @ValueSource(strings={"LOCAL_JWT_JWK_SET_URI", "spring.security.oauth2.resourceserver.jwt.jwk-set-uri", "pago.fixtures.enabled", "PAGO_FIXTURES_ENABLED"})
    void rejectsIdentityOrFixtures(String key) { var e=safe().withProperty(key,"true");
        assertThrows(IllegalStateException.class, () -> new AwsSafety(e).afterPropertiesSet()); }
    @Test void rejectsH2AndDisabledIntegration() { var e=safe().withProperty("spring.datasource.url","jdbc:h2:mem:unsafe");
        assertThrows(IllegalStateException.class, () -> new AwsSafety(e).afterPropertiesSet());
        var disabled=safe().withProperty("pago.operations.remote-enabled","false");
        assertThrows(IllegalStateException.class, () -> new AwsSafety(disabled).afterPropertiesSet()); }
}
