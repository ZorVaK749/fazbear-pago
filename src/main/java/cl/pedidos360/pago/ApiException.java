package cl.pedidos360.pago;

public class ApiException extends RuntimeException {
    final int status;
    final String code;

    ApiException(int status, String code) {
        super(code);
        this.status = status;
        this.code = code;
    }
}
