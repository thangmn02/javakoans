public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.check("Equal numbers", Solution.same(7, 7));
        KoanChecks.check("Different numbers", !Solution.same(7, 9));
        KoanChecks.check("Equal negatives", Solution.same(-4, -4));
        KoanChecks.done();
    }
}
