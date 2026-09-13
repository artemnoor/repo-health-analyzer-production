import java.util.List;

class IterativeMethodsWithFilterAndInclude {
  public static void main(String[] args) {
    List<String> animals = List.of("dog", "cat", "bear", "tiger");

    animals.stream()
        .filter(animal -> animal.length() > 3)
        .forEach(animal -> System.out.println(animal));

    if (animals.contains("cat")) {
      System.out.println("Found a cat!");
    }
  }
}
