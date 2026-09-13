import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

class SingletonMethodsWithParams {
  public static List<String> bar(Object dog, Object cat) {
    return Arrays.asList(dog, cat).stream()
        .map(animal -> animal.toString())
        .collect(Collectors.toList());
  }
}
