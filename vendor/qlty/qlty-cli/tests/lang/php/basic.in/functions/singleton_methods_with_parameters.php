<?php
  class Foo {
    public static function bar($dog, $cat) {
      return array_map(function($animal) {
        return strval($animal);
      }, [$dog, $cat]);
    }
  }
?>
