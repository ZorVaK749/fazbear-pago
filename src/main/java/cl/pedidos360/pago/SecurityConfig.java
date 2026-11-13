package cl.pedidos360.pago;

import java.util.UUID;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.core.annotation.Order;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.filter.OncePerRequestFilter;
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
                          @Value("${pago.security.audience}") String audience,
                          @Value("${LOCAL_JWT_JWK_SET_URI:}") String localJwks, Environment environment) {
        String keys = "https://login.microsoftonline.com/" + UUID.fromString(tenant) + "/discovery/v2.0/keys";
        if (!localJwks.isBlank()) {
            if (!environment.acceptsProfiles(Profiles.of("ev3-local"))) throw new IllegalStateException("LOCAL_JWKS_REQUIRES_LOCAL_PROFILE");
            keys = localJwks;
        }
        var decoder = NimbusJwtDecoder.withJwkSetUri(keys).build();
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
    @Order(1)
    SecurityFilterChain internalSecurity(HttpSecurity http, @Value("${INTERNAL_SERVICE_KEY:}") String key) throws Exception {
        var filter = new OncePerRequestFilter() {
            @Override
            protected void doFilterInternal(jakarta.servlet.http.HttpServletRequest request,
                                            jakarta.servlet.http.HttpServletResponse response,
                                            jakarta.servlet.FilterChain chain) throws java.io.IOException, jakarta.servlet.ServletException {
                String presented = request.getHeader("X-Service-Key");
                if (key.length() < 32 || presented == null || !MessageDigest.isEqual(key.getBytes(StandardCharsets.UTF_8), presented.getBytes(StandardCharsets.UTF_8))) {
                    response.setStatus(401); response.setContentType("application/json");
                    response.getWriter().write("{\"code\":\"UNAUTHORIZED_SERVICE\"}"); return;
                }
                SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken("internal-service", null,
                        java.util.List.of(new SimpleGrantedAuthority("SERVICE_PAYMENT_READ"))));
                chain.doFilter(request, response);
            }
        };
        return http.securityMatcher("/internal/**").csrf(c -> c.disable())
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a -> a.anyRequest().hasAuthority("SERVICE_PAYMENT_READ"))
                .addFilterBefore(filter, UsernamePasswordAuthenticationFilter.class).build();
    }

    @Bean
    @Order(2)
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
