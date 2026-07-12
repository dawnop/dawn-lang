// Driver for the SAM-conversion spike. Plays the role of "the rest of the Dawn
// program": consumes the SAMs built by the ASM-generated SpikeSam class, boots
// jdk.httpserver with a virtual-thread executor, requests itself once, prints
// deterministic output. Run on JVM and as a native-image binary; outputs must
// be byte-identical.

import com.sun.net.httpserver.HttpServer;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.concurrent.Executors;

public class SpikeMain {
    public static void main(String[] args) throws Exception {
        SpikeSam.mkRunnable().run();
        System.out.println(SpikeSam.mkSupplier("dawn").get());

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", SpikeSam.mkHandler());
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.start();
        int port = server.getAddress().getPort();

        HttpResponse<String> resp = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/")).build(),
                HttpResponse.BodyHandlers.ofString());
        System.out.println("http " + resp.statusCode() + ": " + resp.body());
        server.stop(0);
    }
}
