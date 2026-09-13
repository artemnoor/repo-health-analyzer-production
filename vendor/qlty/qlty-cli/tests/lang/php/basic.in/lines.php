<?php
  function f1() {
    $sourceFile = tempnam(sys_get_temp_dir(), "ruby") . ".rb";
    file_put_contents($sourceFile, "foo(...args)");
    $tree = parse($sourceFile);

    bar();
  }

  // Foo
  function f2() {
    bar(); // does not count as comment line
  }

  // multi-line comment
  /*

  line1
  line2

  line4
  */

  function f3() {
    bar();
  }
?>
