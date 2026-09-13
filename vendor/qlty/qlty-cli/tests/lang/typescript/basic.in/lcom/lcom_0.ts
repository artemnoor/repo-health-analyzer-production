// lcom = 0 for all the tests in this file, totalling 0

function foo(this: any) {
  return this.bar;
}

class Klass {
  constructor() {}

  foo(): null {
    return null;
  }
}

class Klass {
  constructor() {}

  foo(): any {
    return bar.baz;
  }
}
