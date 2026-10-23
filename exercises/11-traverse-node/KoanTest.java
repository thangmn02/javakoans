public class KoanTest {
    public static void main(String[] args) {
        Solution.Node list = new Solution.Node(6,"Gin",new Solution.Node(10,"An",new Solution.Node(14,"Lam",null)));
        KoanChecks.eq("First Node", "Gin", Solution.get(list,6));
        KoanChecks.eq("Middle Node", "An", Solution.get(list,10));
        KoanChecks.eq("Last Node", "Lam", Solution.get(list,14));
        KoanChecks.eq("Missing key", null, Solution.get(list,99));
        KoanChecks.eq("Head null", null, Solution.get(null,6));
        KoanChecks.done();
    }
}
