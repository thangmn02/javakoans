public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Empty array", 0, Solution.sumEvens(new int[]{}));
        KoanChecks.eq("Odd and even", 6, Solution.sumEvens(new int[]{1,2,3,4}));
        KoanChecks.eq("With negatives", -2, Solution.sumEvens(new int[]{-4,-3,2,9}));
        KoanChecks.done();
    }
}
