class Main {
    public static void notNested(String foo, String bar) {
        if (("cat".equals(foo) && "dog".equals(bar)) || ("dog".equals(foo) && "cat".equals(bar))) {
            System.out.println("Got a cat and a dog!");
        } else {
            System.out.println("Got nothing");
        }
    }

    public static void f0(boolean bar, boolean baz, boolean qux, boolean quux) {
        if (bar) {
            if (baz) {
                if (qux) {
                    if (quux) {
                        System.out.println("Not deeply nested enough!");
                    }
                }
            }
        }
    }

    public static void f1(boolean bar, boolean baz, boolean qux, boolean quux) {
        if (bar) {
            if (baz) {
                if (qux) {
                    if (quux) {
                        System.out.println("Deeply nested!");
                    }
                }
            }
        }
    }

    public static String f2(int foo) {
        switch (foo) {
            case 1:
                return "bar1";
            case 2:
                return "bar2";
            case 3:
                return "bar3";
            case 4:
                return "bar4";
            case 5:
                return "bar5";
            case 6:
                return "bar6";
            case 7:
                return "bar7";
            case 8:
                return "bar8";
            case 9:
                return "bar9";
            case 10:
                return "bar10";
            default:
                throw new IllegalArgumentException("Invalid foo value");
        }
    }
}
