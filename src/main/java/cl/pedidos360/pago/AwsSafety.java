package cl.pedidos360.pago;

import org.springframework.beans.factory.InitializingBean;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/** Fail closed before starting an AWS-profile service with laboratory configuration. */
@Component
@Profile("ev3-aws")
public class AwsSafety implements InitializingBean {
    private final Environment env;
    public AwsSafety(Environment env) { this.env = env; }
    @Override public void afterPropertiesSet() {
        if (env.matchesProfiles("local", "ev3-local", "test")
                || !env.getProperty("LOCAL_JWT_JWK_SET_URI", "").isBlank()
                || !env.getProperty("spring.security.oauth2.resourceserver.jwt.jwk-set-uri", "").isBlank()
                || env.getProperty("pago.fixtures.enabled", Boolean.class, false)
                || env.getProperty("PAGO_FIXTURES_ENABLED", Boolean.class, false)
                || !env.getProperty("spring.datasource.url", "").startsWith("jdbc:postgresql:")
                || !env.getProperty("pago.operations.remote-enabled", Boolean.class, false)
                || !env.getProperty("pago.kafka.enabled", Boolean.class, false)
                || env.getProperty("INTERNAL_SERVICE_KEY", "").length() < 32)
            throw new IllegalStateException("UNSAFE_EV3_AWS_CONFIGURATION");
    }
}
