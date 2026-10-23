public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Multi-element array", 42, Solution.last(new int[]{7,10,42}));
        KoanChecks.eq("Single element", -3, Solution.last(new int[]{-3}));
        KoanChecks.eq("Empty array", -1, Solution.last(new int[]{}));
        KoanChecks.done();
    }
}
