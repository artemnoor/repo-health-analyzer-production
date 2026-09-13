class Returns {
    void f0() {
    }

    void f1() {
        return;
    }

    void f2() {
        if (true) {
            return;
        } else {
            return;
        }
    }

    void f3() {
        if (true){
            return;
        } else if (true) {
            return;
        } else {
            return;
        }
    }

    void f4() {
        if (true){
            return;
        } else if (true) {
            return;
        } else if (true) {
            return;
        } else {
            return;
        }
    }
}
