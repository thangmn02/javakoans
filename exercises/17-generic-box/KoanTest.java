public class KoanTest {
    public static void main(String[] args) {
        Solution<Integer> a = new Solution<>(42);
        KoanChecks.eq("Integer",42,a.get());
        a.set(7);
        KoanChecks.eq("Update",7,a.get());
        Solution<String> b = new Solution<>("Gin");
        KoanChecks.eq("String", "Gin", b.get());
        KoanChecks.done();
    }
}
