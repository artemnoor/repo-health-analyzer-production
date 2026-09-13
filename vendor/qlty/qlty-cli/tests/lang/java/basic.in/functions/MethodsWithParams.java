class MethodsWithParams {
  private String bar;
  private String baz;

  public MethodsWithParams() {
    this.bar = "";
    this.baz = "";
  }

  public String doSomething(String baz, String bar) {
    this.bar = bar;
    this.baz = baz;
    return this.bar + this.baz;
  }
}
