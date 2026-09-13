<?php
  function foo() {
    array_map(function($animal) {
      echo $animal . "\n";
    }, ["dog", "cat", "bear"]);
  }
?>
