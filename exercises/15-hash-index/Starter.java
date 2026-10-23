public class Solution {
    static int index(int hash, int capacity) {
        // TODO: avoid the Math.abs(Integer.MIN_VALUE) case
        return hash % capacity;
    }
}
