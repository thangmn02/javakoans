public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.check("Same content, different Object", Solution.sameOwner(new String("Gin"), new String("Gin")));
        KoanChecks.check("Different names", !Solution.sameOwner("Gin", "An"));
        KoanChecks.check("Same reference", Solution.sameOwner("Lam", "Lam"));
        KoanChecks.done();
    }
}
