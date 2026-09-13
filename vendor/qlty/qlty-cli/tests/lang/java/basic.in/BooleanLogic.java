class BooleanLogic {
    int foo;
    int bar;

    void f0() {
        var x = foo - bar + 1;
    }
}

class BooleanLogic1 {
    boolean foo;
    boolean bar;
    boolean baz;
    boolean qux;

    void f1() {
        if (foo && bar && baz && qux) {
            return;
        }
    }
}
