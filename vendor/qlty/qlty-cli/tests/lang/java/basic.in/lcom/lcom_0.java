// lcom = 0 for all the tests in this file, totalling 0

class Foo {
  private String bar;

  public String foo() {
    return this.bar;
  }
}

class Klass1 {
  public Klass1() {
  }

  public Object foo() {
    return null;
  }
}

class Klass2 {
  private Bar bar;

  public Klass2(Bar bar) {
    this.bar = bar;
  }

  public Object foo() {
    return this.bar.getBaz();
  }
}

class Bar {
  private String baz;

  public String getBaz() {
    return this.baz;
  }
}
