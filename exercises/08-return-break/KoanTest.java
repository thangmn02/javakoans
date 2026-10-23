public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Found at the end", 9, Solution.firstPositive(new int[]{-4,0,-2,9,10}));
        KoanChecks.eq("Found at the start", 3, Solution.firstPositive(new int[]{3,5}));
        KoanChecks.eq("Not found", -1, Solution.firstPositive(new int[]{0,-2}));
        KoanChecks.done();
    }
}
