public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Single number", 1, Solution.sumTo(1));
        KoanChecks.eq("Sum 1..5", 15, Solution.sumTo(5));
        KoanChecks.eq("Input 0", 0, Solution.sumTo(0));
        KoanChecks.eq("Negative input", 0, Solution.sumTo(-3));
        KoanChecks.done();
    }
}
