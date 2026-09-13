package cognitive;

class CountConditionalAssignment {
  public static void main(String[] args) {
    int bar = 0;
    bar = bar != 0 ? bar : 10;
    int foo = 0;
    foo = foo != 0 && foo != 10 ? foo : 10;
  }
}
