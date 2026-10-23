public class KoanTest {
    public static void main(String[] args) {
        Solution.Box a = new Solution.Box("An");
        Solution.Box b = a;
        Solution.rename(b, "Minh");
        KoanChecks.eq("Change visible through a", "Minh", a.value);
        KoanChecks.check("a and b are still the same Object", a == b);
        KoanChecks.done();
    }
}
