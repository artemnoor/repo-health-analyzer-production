<?php
  // lcom = 0 for all the tests in this file, totaling 0

  function foo() {
    return $this->bar;
  }

  class Klass {
    private $bar;

    public function __construct() {}

    public function foo() {
      $bar = new class implements Baz {
        private $bee;
      };

      return null;
    }
  }

  class Klass {
    public function __construct() {}

    public function foo() {
      return $bar->baz;
    }
  }
?>
