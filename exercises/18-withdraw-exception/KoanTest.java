public class KoanTest {
    public static void main(String[] args) {
        Solution b = new Solution(100);
        b.withdraw(30);
        KoanChecks.eq("Valid withdrawal",70,b.balance());
        boolean badAmount=false;
        try{b.withdraw(0);}catch(IllegalArgumentException ex){badAmount=true;}
        KoanChecks.check("Reject withdrawing 0",badAmount);
        KoanChecks.eq("Unchanged after failure 1",70,b.balance());
        boolean insufficient=false;
        try{b.withdraw(90);}catch(IllegalStateException ex){insufficient=true;}
        KoanChecks.check("Insufficient funds",insufficient);
        KoanChecks.eq("Unchanged after failure 2",70,b.balance());
        KoanChecks.done();
    }
}
