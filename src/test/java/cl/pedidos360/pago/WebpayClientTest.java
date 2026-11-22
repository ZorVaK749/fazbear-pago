package cl.pedidos360.pago;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import java.net.URI;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatNoException;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class WebpayClientTest {
    @Test
    void acceptsBothApprovedCheckoutPathsAndRejectsOtherCallbackPaths() {
        for (String path : new String[]{"/checkout/webpay", "/ev3/checkout/webpay"}) {
            assertThatNoException().isThrownBy(() -> new WebpayClient("597055555532", "test-only",
                    URI.create("https://shop.example.test" + path)));
        }
        assertThatThrownBy(() -> new WebpayClient("597055555532", "test-only",
                URI.create("https://shop.example.test/ev3/checkout")))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void roundTripsOfficialRestFieldsAndIgnoresCardDetails() {
        var builder = RestClient.builder().baseUrl(WebpayClient.HOST);
        var mock = MockRestServiceServer.bindTo(builder).build();
        var client = new WebpayClient(builder.build(), "https://shop.example.test/checkout/webpay");
        String path = WebpayClient.HOST + WebpayClient.TRANSACTIONS;
        String token = "sandbox-reference-for-test";
        mock.expect(requestTo(path)).andExpect(method(HttpMethod.POST))
                .andExpect(content().json("""
                    {"buy_order":"order-1","session_id":"session-1","amount":12990,
                     "return_url":"https://shop.example.test/checkout/webpay"}
                    """))
                .andRespond(withSuccess("""
                    {"token":"sandbox-reference-for-test","url":"https://webpay3gint.transbank.cl/webpayserver/initTransaction"}
                    """, MediaType.APPLICATION_JSON));
        mock.expect(requestTo(path + "/" + token)).andExpect(method(HttpMethod.PUT))
                .andExpect(header("Content-Type", "application/json"))
                .andRespond(withSuccess("""
                    {"status":"AUTHORIZED","amount":12990,"buy_order":"order-1","session_id":"session-1",
                     "response_code":0,"card_detail":{"card_number":"0000"}}
                    """, MediaType.APPLICATION_JSON));
        mock.expect(requestTo(path + "/" + token)).andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess("""
                    {"status":"FAILED","amount":12990,"buy_order":"order-1","session_id":"session-1","response_code":-1}
                    """, MediaType.APPLICATION_JSON));

        assertThat(client.create("order-1", "session-1", 12990).token()).isEqualTo(token);
        assertThat(client.commit(token).responseCode()).isZero();
        assertThat(client.status(token).status()).isEqualTo("FAILED");
        mock.verify();
    }
}
