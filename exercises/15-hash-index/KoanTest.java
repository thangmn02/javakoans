public class KoanTest {
    public static void main(String[] args) {
        KoanChecks.eq("Hash 14 capacity 4",2,Solution.index(14,4));
        KoanChecks.eq("Negative hash",3,Solution.index(-1,4));
        KoanChecks.eq("MIN_VALUE and capacity 5",2,Solution.index(Integer.MIN_VALUE,5));
        KoanChecks.check("Result in range",Solution.index(-123,17)>=0 && Solution.index(-123,17)<17);
        KoanChecks.done();
    }
}
