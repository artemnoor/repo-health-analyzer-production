// lcom=1

class Klass {
  String bar;

  public Klass() {
  }

  public String getBar() {
    return this.bar;
  }

  public String foo() {
    return this.getBar();
  }
}
