// lcom=2

class KlassA {
  String aaa;
  String bbb;

  public String getBbb() {
    return this.aaa;
  }

  public String getAaa() {
    return this.aaa;
  }

  String foo() {
    return this.getAaa();
  }

  String bar() {
    return this.getBbb();
  }
}

class KlassB {
  String baz;

  public String getBar() {
    return this.baz;
  }

  String foo() {
    return this.getBar();
  }

  String bar() {
    return this.getBar();
  }
}
