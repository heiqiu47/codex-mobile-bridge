import io.github.try2love.codexbridge.GatewayURL;

public class URLReuseTests {
    public static void main(String[] args) {
        String base = "https://gateway.example/d/" + "a".repeat(32);
        for (String page : new String[]{base+"/", base+"/#chat", base+"/?client=claude#chat"}) {
            if (!GatewayURL.isChatPage(page, base)) throw new AssertionError(page);
        }
        for (String page : new String[]{null, "about:blank", base+"/api/auth", base+"/?token=secret",
                "https://gateway.example/", "https://gateway.example/d/"+"b".repeat(32)+"/",
                "https://gateway.example.evil/", "http://gateway.example/", base+"/%2e%2e/"}) {
            if (GatewayURL.isChatPage(page, base)) throw new AssertionError(page);
        }
        System.out.println("Java: notification page reuse URL boundaries passed");
    }
}
