package cl.pedidos360.pago;

import static cl.pedidos360.pago.PaymentModels.*;

import java.util.UUID;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/pagos/webpay")
@ConditionalOnProperty(name = "pago.webpay.enabled", havingValue = "true")
class WebpayController {
    private final WebpayService service;
    private final QuoteImportService quotes;

    WebpayController(WebpayService service, QuoteImportService quotes) {
        this.service = service;
        this.quotes = quotes;
    }

    record Start(@NotNull UUID operacionId) {}

    @GetMapping("/capacidad")
    ResponseEntity<Void> available() {
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @PostMapping
    ResponseEntity<WebpayService.Redirect> start(@AuthenticationPrincipal Jwt jwt,
            @RequestHeader("Idempotency-Key") String key, @Valid @RequestBody Start body) {
        Owner owner = Owner.from(jwt);
        quotes.ensure(owner, body.operacionId(), "Bearer " + jwt.getTokenValue());
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(service.start(owner, body.operacionId(), key));
    }

    @PostMapping("/retorno")
    ResponseEntity<Payment> finish(@AuthenticationPrincipal Jwt jwt, @RequestBody WebpayService.Return body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(service.finish(Owner.from(jwt), body));
    }

    @PostMapping("/{id}/estado")
    ResponseEntity<Payment> recover(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(service.recover(Owner.from(jwt), id));
    }
}
