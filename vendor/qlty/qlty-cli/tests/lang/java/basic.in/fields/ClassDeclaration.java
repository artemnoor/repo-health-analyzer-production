package fields;

class Foo {
  String bar;
  String baz;

  // Constructor
  public Foo() {
    this.bar = "";
    this.baz = "";
  }
}

public class ClassDeclaration {
  public static void main(String[] args) {
    System.out.println(doSomething());
  }

  public static String doSomething() {
    Foo foo = new Foo();
    foo.bar = "Hello";
    foo.baz = "World";
    return foo.bar + foo.baz;
  }
}
