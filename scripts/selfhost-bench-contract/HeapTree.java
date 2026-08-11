/*
 * Keep process-tree and heap probes independent from the Dawn compiler. The
 * fixture stays alive long enough for /proc sampling and same-JDK jcmd attach.
 */

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

public final class HeapTree {
    private static final List<byte[]> RETAINED = new ArrayList<>();

    private HeapTree() {}

    private static void allocate(int mebibytes) {
        byte[] memory = new byte[mebibytes * 1024 * 1024];
        for (int index = 0; index < memory.length; index += 4096) {
            memory[index] = 1;
        }
        RETAINED.add(memory);
    }

    private static Process spawn(String heap, String mode, Path work) throws IOException {
        Path java = Path.of(System.getProperty("java.home"), "bin", "java");
        return new ProcessBuilder(
                java.toString(),
                "-Xmx" + heap,
                "-cp",
                System.getProperty("java.class.path"),
                "HeapTree",
                mode,
                work.toString())
            .inheritIO()
            .start();
    }

    private static void ready(Path work, String mode) throws IOException {
        Files.writeString(work.resolve("ready." + mode), Long.toString(ProcessHandle.current().pid()));
    }

    private static void waitForRelease(Path work, String release) throws Exception {
        long deadline = System.nanoTime() + 20_000_000_000L;
        while (!Files.exists(work.resolve(release))) {
            if (System.nanoTime() >= deadline) {
                throw new IllegalStateException("timed out waiting for " + release);
            }
            Thread.sleep(10);
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: HeapTree MODE WORK");
        }
        String mode = args[0];
        Path work = Path.of(args[1]);
        Process child = null;
        switch (mode) {
            case "parent" -> {
                allocate(8);
                child = spawn("96m", "child", work);
            }
            case "child" -> {
                allocate(12);
                child = spawn("64m", "grandchild", work);
            }
            case "grandchild" -> allocate(16);
            case "sibling" -> allocate(24);
            default -> throw new IllegalArgumentException("unknown mode: " + mode);
        }
        ready(work, mode);
        waitForRelease(work, mode.equals("sibling") ? "release.sibling" : "release.tree");
        if (child != null && child.waitFor() != 0) {
            throw new IllegalStateException("child exited nonzero");
        }
    }
}
