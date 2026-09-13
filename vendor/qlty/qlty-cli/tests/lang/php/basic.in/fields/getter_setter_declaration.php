<?php
  class MyClass {
    private $_field;

    public function getFieldName() {
      return $this->_field;
    }

    public function setFieldName($value) {
      $this->_field = $value;
    }
  }
?>
