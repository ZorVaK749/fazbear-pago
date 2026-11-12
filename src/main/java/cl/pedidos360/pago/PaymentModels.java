package cl.pedidos360.pago;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import org.springframework.security.oauth2.jwt.Jwt;

public final class PaymentModels {
    private PaymentModels() {}

    public record Owner(UUID tenant, UUID oid) {
        static Owner from(Jwt jwt) {
            return new Owner(UUID.fromString(jwt.getClaimAsString("tid")), UUID.fromString(jwt.getClaimAsString("oid")));
        }
    }

    public record PaymentRequest(@NotNull UUID operacionId,
                                 @NotNull @Pattern(regexp = "SIMULADO") String metodo,
                                 @NotNull @Pattern(regexp = "sim-[a-z0-9-]{1,60}") String instrumentoPruebaId) {}

    public record Payment(UUID pagoId, UUID operacionId, String estado, BigDecimal importe,
                          String moneda, boolean simulacion, Instant creadoEn) {}

    public record Result(Payment payment, boolean replay) {}
}
