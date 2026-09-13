import java.util.List;

class IterativeMap {
  public static void main(String[] args) {
    List<String> animals = List.of("dog", "cat", "bear");

    animals.stream().map(animal -> {
      System.out.println(animal);
      return animal;
    });
  }
}
