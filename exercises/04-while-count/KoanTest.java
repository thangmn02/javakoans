public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Number 0", 1, Solution.digits(0));
        KoanChecks.eq("Single digit", 1, Solution.digits(7));
        KoanChecks.eq("Number 905", 3, Solution.digits(905));
        KoanChecks.eq("Large number", 10, Solution.digits(Integer.MAX_VALUE));
        KoanChecks.done();
    }
}
