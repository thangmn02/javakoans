import java.util.Objects;

/** Lightweight, dependency-free test API for KoanForge exercises. */
public final class KoanChecks {
    private static int passed = 0;
    private static int failed = 0;
    private KoanChecks() { }

    public static void check(String name, boolean condition) {
        if (condition) {
            passed++;
            System.out.println("PASS\t" + safe(name));
        } else {
            failed++;
            System.out.println("FAIL\t" + safe(name) + "\tCondition returned false");
        }
    }

    public static void eq(String name, Object expected, Object actual) {
        if (Objects.deepEquals(expected, actual)) {
            passed++;
            System.out.println("PASS\t" + safe(name));
        } else {
            failed++;
            System.out.println("FAIL\t" + safe(name) + "\tExpected: " + safe(String.valueOf(expected)) + ", got: " + safe(String.valueOf(actual)));
        }
    }

    public static void done() {
        System.out.println("RESULT\t" + passed + "\t" + failed);
        if (failed != 0) System.exit(1);
    }

    private static String safe(String s) {
        return s.replace('\t',' ').replace('\r',' ').replace('\n',' ');
    }
}
