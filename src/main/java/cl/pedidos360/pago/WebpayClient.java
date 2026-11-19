package cl.pedidos360.pago;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.net.URI;
import java.math.BigDecimal;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
@ConditionalOnProperty(name = "pago.webpay.enabled", havingValue = "true")
class WebpayClient {
    static final String HOST = "https://webpay3gint.transbank.cl";
    static final String FORM = HOST + "/webpayserver/initTransaction";
    static final String TRANSACTIONS = "/rswebpaytransaction/api/webpay/v1.2/transactions";
    private final RestClient provider;
    private final String returnUrl;

    @Autowired
    WebpayClient(@Value("${pago.webpay.commerce-code:}") String commerceCode,
                 @Value("${pago.webpay.api-key:}") String key,
                 @Value("${pago.webpay.return-url:}") URI returnUrl) {
        if (!commerceCode.matches("[0-9]{12}") || key.isBlank()
                || !"https".equals(returnUrl.getScheme()) || returnUrl.getHost() == null
                || returnUrl.getUserInfo() != null || returnUrl.getQuery() != null || returnUrl.getFragment() != null
                || !"/checkout/webpay".equals(returnUrl.getPath())) {
            throw new IllegalStateException("WEBPAY_INTEGRATION_CONFIGURATION_REQUIRED");
        }
        this.returnUrl = returnUrl.toString();
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(3500);
        provider = RestClient.builder().baseUrl(HOST).requestFactory(factory)
                .defaultHeader("Tbk-Api-Key-Id", commerceCode)
                .defaultHeader("Tbk-Api-Key-Secret", key).build();
    }

    WebpayClient(RestClient provider, String returnUrl) {
        this.provider = provider;
        this.returnUrl = returnUrl;
    }

    Created create(String order, String session, int amount) {
        return provider.post().uri(TRANSACTIONS).body(Map.of(
                "buy_order", order, "session_id", session, "amount", amount, "return_url", returnUrl))
                .retrieve().body(Created.class);
    }

    Outcome commit(String token) {
        return provider.put().uri(TRANSACTIONS + "/{token}", token).retrieve().body(Outcome.class);
    }

    Outcome status(String token) {
        return provider.get().uri(TRANSACTIONS + "/{token}", token).retrieve().body(Outcome.class);
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Created(String token, String url) {
        @Override public String toString() { return "Webpay transaction created"; }
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Outcome(String status, BigDecimal amount, @JsonProperty("buy_order") String order,
                   @JsonProperty("session_id") String session, @JsonProperty("response_code") Integer responseCode) {}
}
