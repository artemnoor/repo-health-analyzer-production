// lcom=1

class Klass {
  public Klass() {
  }

  public String foo() {
    return this.baz();
  }

  private String baz() {
    return "baz method called";
  }
}
