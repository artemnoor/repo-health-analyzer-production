class FunctionComplexity {
    void simple() {
    }

    void complex() {
        int bar = 42;
        if (bar > 0) {
            if (bar > 10) {
                if (bar < 20) {
                    if (bar % 2 == 0) {
                        if (bar % 3 == 0) {
                            System.out.println("Nested!");
                        }
                    }
                }
            }
        }
    }
}
