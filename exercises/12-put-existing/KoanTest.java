public class KoanTest {
    static int count(Solution.Node n){int c=0;while(n!=null && c<100){c++;n=n.next;}return c;}
    public static void main(String[] args) {
        Solution.Node h = Solution.put(null,6,"Gin");
        KoanChecks.check("Create head when null",h!=null && h.key==6 && "Gin".equals(h.value));
        h = Solution.put(h,10,"An");
        KoanChecks.check("Append Node",h!=null && h.next!=null && h.next.key==10);
        h = Solution.put(h,10,"Minh");
        KoanChecks.check("Update value",h!=null && h.next!=null && "Minh".equals(h.next.value));
        KoanChecks.eq("No duplicate key",2,count(h));
        KoanChecks.done();
    }
}
