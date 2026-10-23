public class KoanTest {
    static int count(Solution.Node[] a){int n=0;for(Solution.Node h:a){int limit=0;while(h!=null&&limit++<100){n++;h=h.next;}}return n;}
    static String find(Solution.Node[] a,int key){Solution.Node h=a[key%a.length];int limit=0;while(h!=null&&limit++<100){if(h.key==key)return h.value;h=h.next;}return null;}
    public static void main(String[] args) {
        Solution.Node[] old = new Solution.Node[4];
        old[1]=new Solution.Node(1,"A",new Solution.Node(5,"B",new Solution.Node(9,"C",new Solution.Node(13,"D",null))));
        Solution.Node[] newer=Solution.resize(old);
        KoanChecks.eq("Capacity doubled",8,newer.length);
        KoanChecks.eq("Entry count preserved",4,count(newer));
        KoanChecks.eq("Read 1", "A", find(newer,1));
        KoanChecks.eq("Read 5", "B", find(newer,5));
        KoanChecks.eq("Read 9", "C", find(newer,9));
        KoanChecks.eq("Read 13", "D", find(newer,13));
        KoanChecks.done();
    }
}
