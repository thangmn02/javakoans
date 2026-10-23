public class KoanTest {
    public static void main(String[] args) {
        Solution wallet = new Solution(100);
        KoanChecks.eq("Initial balance", 100, wallet.balance());
        wallet.deposit(50);
        KoanChecks.eq("Deposit", 150, wallet.balance());
        wallet.deposit(-999);
        KoanChecks.eq("Ignore negative deposit", 150, wallet.balance());
        KoanChecks.done();
    }
}
