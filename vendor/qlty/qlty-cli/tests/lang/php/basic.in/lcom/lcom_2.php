<?php
  // lcom=2

  class KlassA {
    public function __construct() {}

    public function foo() {
      return $this->aaa;
    }

    public function bar() {
      return $this->bbb;
    }
  }

  class KlassB {
    public function __construct() {}

    public function foo() {
      return $this->baz;
    }

    public function bar() {
      return $this->baz;
    }
  }
?>
