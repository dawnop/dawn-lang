// Delete this offline migration helper after knife 4. The compiler's own AST
// supplies field ownership and code point spans; host text is never a grammar.
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class SpanProbe {
    record Hit(String kind, int at) implements Comparable<Hit> {
        public int compareTo(Hit other) {
            int order = Integer.compare(at, other.at);
            return order == 0 ? kind.compareTo(other.kind) : order;
        }
    }
    static Object field(Object object, String name) throws Exception {
        return object.getClass().getField(name).get(object);
    }
    static Object some(Object value) throws Exception {
        return value.getClass().getName().equals("Option$Some") ? field(value, "value") : null;
    }
    static List<Object> vector(Object value) throws Exception {
        var result = new ArrayList<Object>();
        long count = (Long) field(value, "cnt");
        for (long i = 0; i < count; i++)
            result.add(some(std.pvec.get((std.pvec$Vec) value, i)));
        return result;
    }
    static class Scan {
        final int[] source;
        final Map<Integer, Integer> separators = new HashMap<>();
        final Set<Hit> hits = new TreeSet<>();
        final List<String> strings = new ArrayList<>();
        Scan(String text) throws Exception {
            source = text.codePoints().toArray();
            indexTokens(text, 0);
        }
        void indexTokens(String text, long base) throws Exception {
            var tokens = vector(front.lexer.lex_at(text, base)._0);
            for (int i = 0; i < tokens.size(); i++) {
                Object token = tokens.get(i);
                if (i + 1 < tokens.size() && field(token, "kind").getClass().getName().endsWith("$IDENT") &&
                    field(tokens.get(i + 1), "kind").getClass().getName().endsWith("$COLON")) {
                    separators.put(Math.toIntExact((Long) field(token, "lo")),
                                   Math.toIntExact((Long) field(tokens.get(i + 1), "lo")));
                }
                // Interpolations are lexed at their original code point base,
                // just as the parser does. Ordinary decoded text is not code.
                for (Object segment : vector(field(token, "segs")))
                    if (segment.getClass().getName().endsWith("$SCode"))
                        indexTokens((String) field(segment, "code"), (Long) field(segment, "off"));
            }
        }
        void hit(String kind, long start, String name) {
            int at = Math.toIntExact(start);
            int[] spelling = name.codePoints().toArray();
            if (at < 0 || at + spelling.length > source.length) return;
            for (int i = 0; i < spelling.length; i++)
                if (source[at + i] != spelling[i]) return;
            Integer separator = separators.get(at);
            if (separator != null && separator < source.length && source[separator] == ':')
                hits.add(new Hit(kind, separator));
        }
        void walk(Object object, String context) throws Exception {
            if (object == null || object instanceof String || object instanceof Number ||
                object instanceof Boolean) return;
            String name = object.getClass().getName();
            if (name.equals("std.pvec$Vec")) {
                for (Object item : vector(object)) walk(item, context);
                return;
            }
            if (name.endsWith("$ERecord")) context = "R";
            if (name.endsWith("$EApply") || name.endsWith("$EMethod")) context = "N";
            if (name.equals("front.ast$Arg")) {
                Object label = some(field(object, "name"));
                if (label != null) hit(context, (Long) field(object, "lo"), (String) label);
            }
            if (name.equals("front.ast$PatArg")) {
                Object label = some(field(object, "name"));
                if (label != null) hit("P", (Long) field(object, "nlo"), (String) label);
            }
            if (name.endsWith("$SPText")) strings.add((String) field(object, "v"));
            if (name.startsWith("front.ast$") || name.startsWith("dawn.rt.Tuple") ||
                name.equals("Option$Some"))
                for (Field member : object.getClass().getFields())
                    if (!Modifier.isStatic(member.getModifiers())) walk(member.get(object), context);
        }
    }
    static Scan parse(String text) throws Exception {
        var result = front.parser.parse_module(text);
        var scan = new Scan(text);
        scan.walk(result._0, "?");
        return scan;
    }
    static Set<Hit> fragment(String text) throws Exception {
        Set<Hit> hits = new TreeSet<>();
        for (String prefix : List.of("", "fn probe() = ", "fn probe() = {\n")) {
            String suffix = prefix.endsWith("{\n") ? "\n}" : "";
            Scan scan = parse(prefix + text + suffix);
            int shift = prefix.codePointCount(0, prefix.length());
            for (Hit hit : scan.hits) {
                int at = hit.at - shift;
                if (at >= 0 && at < text.codePointCount(0, text.length()))
                    hits.add(new Hit(hit.kind, at));
            }
        }
        return hits;
    }
    static String encoded(String text) {
        return Base64.getEncoder().encodeToString(text.getBytes(StandardCharsets.UTF_8));
    }
    public static void main(String[] args) throws Exception {
        boolean fragments = args.length > 1 && args[1].equals("fragments");
        int file = 0;
        for (String path : Files.readAllLines(Path.of(args[0]))) {
            String text = Files.readString(Path.of(path));
            if (fragments) {
                for (Hit hit : fragment(text))
                    System.out.println("H\t" + file + "\t" + hit.kind + "\t" + hit.at);
            } else {
                var parsed = front.parser.parse_module(text);
                var scan = new Scan(text);
                scan.walk(parsed._0, "?");
                System.out.println("D\t" + file + "\t" + vector(parsed._1).size());
                for (Hit hit : scan.hits)
                    System.out.println("H\t" + file + "\t" + hit.kind + "\t" + hit.at);
                // Repair only an erroneous RHS `=` using its real diagnostic
                // span. Equal-width replacement keeps every original offset.
                // This recovers the three fields lost by the research parser.
                String repaired = text;
                Set<Integer> repairs = new HashSet<>();
                for (int pass = 0; pass < 8; pass++) {
                    int[] cps = repaired.codePoints().toArray();
                    boolean changed = false;
                    for (Object diagnostic : vector(front.parser.parse_module(repaired)._1)) {
                        int at = Math.toIntExact((Long) field(diagnostic, "lo"));
                        if (field(diagnostic, "msg").equals("expected an expression, found `=`") &&
                            at < cps.length && cps[at] == '=' && repairs.add(at)) {
                            cps[at] = '0'; changed = true;
                        }
                    }
                    if (!changed) break;
                    repaired = new String(cps, 0, cps.length);
                    for (Hit hit : parse(repaired).hits)
                        if (!scan.hits.contains(hit) && scan.source[hit.at] == ':')
                            System.out.println("R\t" + file + "\t" + hit.kind + "\t" + hit.at);
                }
                int index = 0;
                for (String value : scan.strings) {
                    if (value.contains(":")) {
                        for (Hit hit : fragment(value))
                            System.out.println("S\t" + file + "\t" + index + "\t" + hit.kind +
                                "\t" + hit.at + "\t" + encoded(value));
                    }
                    index++;
                }
            }
            file++;
        }
    }
}
