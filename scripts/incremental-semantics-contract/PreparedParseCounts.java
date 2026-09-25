package contract;

import java.nio.file.Path;

/** Share the strict method-entry observer, with loader-specific intervals. */
public final class PreparedParseCounts {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected subject jar");
        SourceParseCounts.verify(Path.of(args[0]), "dawn$pkg$selfhost.contract.prepared_parse_counts", "prepared parse invocation counts",
            new String[]{"project_on", "project_off", "standalone", "session_consumer"},
            new long[][]{{3, 3, 3}, {3, 0, 0}, {1, 1, 1}, {0, 0, 0}});
    }
}
