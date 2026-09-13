import java.io.File;
import java.io.FileWriter;
import java.io.IOException;

class Main {
    public static void f1() {
        try {
            File sourceFile = File.createTempFile("ruby", ".kt");
            try (FileWriter writer = new FileWriter(sourceFile)) {
                writer.write("foo(...args)");
            }

            Object tree = parseFile(sourceFile);

            bar();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    public static Object parseFile(File file) {
        return new Object();
    }

    // Foo
    public static void f2() {
        bar(); // does not count as comment line
    }

    // multi-line comment
    /*
     * line1
     * line2
     * line4
     */

    public static void f3() {
        bar();
    }

    public static void bar() {
        System.out.println("bar() called");
    }
}
