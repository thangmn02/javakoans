public class KoanTest {
    static Solution.Node list(){return new Solution.Node(6,new Solution.Node(10,new Solution.Node(14,null)));}
    static String keys(Solution.Node h){StringBuilder b=new StringBuilder();int cap=0;while(h!=null && cap++<20){b.append(h.key).append(',');h=h.next;}return b.toString();}
    public static void main(String[] args) {
        KoanChecks.eq("Remove middle", "6,14,", keys(Solution.remove(list(),10)));
        KoanChecks.eq("Remove head", "10,14,", keys(Solution.remove(list(),6)));
        KoanChecks.eq("Remove last", "6,10,", keys(Solution.remove(list(),14)));
        KoanChecks.eq("Not found", "6,10,14,", keys(Solution.remove(list(),99)));
        KoanChecks.eq("Head null",null,Solution.remove(null,10));
        KoanChecks.done();
    }
}
