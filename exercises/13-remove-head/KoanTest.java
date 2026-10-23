public class KoanTest {
    public static void main(String[] args) {
        Solution.Node h = new Solution.Node(6,new Solution.Node(10,new Solution.Node(14,null)));
        Solution.Node newer = Solution.removeHead(h);
        KoanChecks.check("New head has key 10",newer!=null && newer.key==10);
        KoanChecks.check("Node 14 is kept",newer!=null && newer.next!=null && newer.next.key==14);
        KoanChecks.eq("Remove from null head",null,Solution.removeHead(null));
        KoanChecks.done();
    }
}
