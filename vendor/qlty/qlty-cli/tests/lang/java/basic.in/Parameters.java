class Parameters {
    public static void f0() {
    }

    public static void f1(Object dog, Object cat) {
    }

    public static void f2(Object a, Object b, Object c, Object d, Object e, Object f) {
    }

    public static void f3() {
        Object foo = bar(1, 2, 3, 4);
    }

    public static Object bar(int a, int b, int c, int d) {
        return new Object();
    }
}
