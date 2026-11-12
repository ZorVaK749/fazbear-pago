package cl.pedidos360.pago;

import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(ApiException.class)
    ResponseEntity<?> domain(ApiException e) {
        return ResponseEntity.status(e.status).body(Map.of("code", e.code));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class,
            MethodArgumentTypeMismatchException.class})
    ResponseEntity<?> invalid(Exception e) {
        return ResponseEntity.badRequest().body(Map.of("code", "INVALID_REQUEST"));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    ResponseEntity<?> persistence(Exception e) {
        // No SQL/error details, request bodies, credentials or retry loops.
        return ResponseEntity.status(503).body(Map.of("code", "PERSISTENCE_UNAVAILABLE",
                "retry", "Reuse the same Idempotency-Key and content; no automatic retry."));
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<?> unexpected(Exception e) {
        return ResponseEntity.internalServerError().body(Map.of("code", "INTERNAL_ERROR"));
    }
}
