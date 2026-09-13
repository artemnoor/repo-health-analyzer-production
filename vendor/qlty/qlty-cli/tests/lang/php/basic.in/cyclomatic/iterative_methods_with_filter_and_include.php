<?php
  function foo() {
    $animals = ["dog", "cat", "bear", "tiger"];

    array_filter($animals, function($animal) {
      return strlen($animal) > 3;
    });

    foreach ($animals as $animal) {
      echo $animal . "\n";
    }

    if (in_array("cat", $animals)) {
      echo "Found a cat!\n";
    }
  }
?>
