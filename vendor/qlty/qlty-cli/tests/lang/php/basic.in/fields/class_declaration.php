<?php
  class Foo {
    public $bar = "";
    public $baz = "";

    public function __construct() {
      $this->bar = "";
      $this->baz = "";
    }
  }

  function doSomething() {
    $foo = new Foo();
    $foo->bar = "Hello";
    $foo->baz = "World";
    return ($foo->bar . $foo->baz);
  }
?>
