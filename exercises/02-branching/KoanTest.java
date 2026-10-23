public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Negative balance", "DEBT", Solution.classify(-10));
        KoanChecks.eq("Zero balance", "EMPTY", Solution.classify(0));
        KoanChecks.eq("Positive balance", "ACTIVE", Solution.classify(120));
        KoanChecks.done();
    }
}
