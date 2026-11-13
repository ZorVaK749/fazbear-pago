package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

@RestController
public class PaymentController {
    private final PaymentService service;
    private final QuoteImportService quotes;

    PaymentController(PaymentService service, QuoteImportService quotes) { this.service = service; this.quotes = quotes; }

    @GetMapping("/health")
    Map<String, String> health() { return Map.of("status", "UP", "mode", "SIMULATION_ONLY"); }

    @PostMapping("/api/pagos")
    ResponseEntity<Payment> pay(@AuthenticationPrincipal Jwt jwt,
                                @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                @Valid @RequestBody PaymentRequest request) {
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) throw new ApiException(400, "INVALID_IDEMPOTENCY_KEY");
        Owner owner = Owner.from(jwt);
        Result result = service.replayIfPresent(owner, key, request);
        if (result == null) {
            quotes.ensure(owner, request.operacionId(), "Bearer " + jwt.getTokenValue());
            result = service.pay(owner, key, request);
        }
        int status = result.payment().estado().equals("BLOCKED") ? 429 : result.replay() ? 200 : 201;
        return ResponseEntity.status(status)
                .location(URI.create("/api/pagos/" + result.payment().pagoId()))
                .header("Idempotency-Replayed", Boolean.toString(result.replay()))
                .body(result.payment());
    }

    @GetMapping("/api/pagos/{id}")
    Payment get(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.get(Owner.from(jwt), id);
    }

    @GetMapping("/api/pagos/me")
    List<Payment> mine(@AuthenticationPrincipal Jwt jwt, @RequestParam(defaultValue = "50") int limit) {
        return service.mine(Owner.from(jwt), limit);
    }
}
