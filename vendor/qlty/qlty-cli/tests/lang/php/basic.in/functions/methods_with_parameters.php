<?php
  class Foo {
    public $bar;
    public $baz;

    public function __construct() {
      $this->bar = "";
      $this->baz = "";
    }

    public function doSomething($baz, $bar) {
      $this->bar = $bar;
      $this->baz = $baz;
      return ($this->bar . $this->baz);
    }
  }
?>
