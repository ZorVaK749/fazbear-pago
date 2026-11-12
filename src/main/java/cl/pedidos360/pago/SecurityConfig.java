package cl.pedidos360.pago;

import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class SecurityConfig {
    @Bean
    JwtDecoder jwtDecoder(@Value("${pago.security.tenant}") String tenant,
                          @Value("${pago.security.audience}") String audience) {
        var decoder = NimbusJwtDecoder.withJwkSetUri(
                "https://login.microsoftonline.com/" + UUID.fromString(tenant) + "/discovery/v2.0/keys").build();
        decoder.setJwtValidator(validators(tenant, audience));
        return decoder;
    }

    static OAuth2TokenValidator<Jwt> validators(String tenant, String audience) {
        OAuth2TokenValidator<Jwt> claims = jwt -> {
            try {
                String oid = jwt.getClaimAsString("oid");
                boolean valid = tenant.equals(jwt.getClaimAsString("tid"))
                        && jwt.getAudience().contains(audience)
                        && oid != null && UUID.fromString(oid).toString().equalsIgnoreCase(oid)
                        && jwt.getExpiresAt() != null && jwt.getSubject() != null;
                if (valid) return OAuth2TokenValidatorResult.success();
            } catch (RuntimeException ignored) {
                // Fail closed; claims and tokens are never logged.
            }
            return OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token"));
        };
        return new DelegatingOAuth2TokenValidator<>(
                JwtValidators.createDefaultWithIssuer("https://login.microsoftonline.com/" + tenant + "/v2.0"), claims);
    }

    @Bean
    SecurityFilterChain security(HttpSecurity http) throws Exception {
        return http.csrf(c -> c.disable())
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a -> a
                        .requestMatchers(HttpMethod.GET, "/health").permitAll()
                        .requestMatchers("/api/pagos", "/api/pagos/**").hasAuthority("SCOPE_access_as_user")
                        .anyRequest().denyAll())
                .oauth2ResourceServer(o -> o.jwt(j -> {}).authenticationEntryPoint((req, res, ex) -> {
                    res.setStatus(401);
                    res.setHeader("WWW-Authenticate", "Bearer");
                    res.setContentType("application/json");
                    res.getWriter().write("{\"code\":\"UNAUTHORIZED\"}");
                }))
                .exceptionHandling(e -> e.accessDeniedHandler((req, res, ex) -> {
                    res.setStatus(403);
                    res.setContentType("application/json");
                    res.getWriter().write("{\"code\":\"FORBIDDEN\"}");
                })).build();
    }
}
