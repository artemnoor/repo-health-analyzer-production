<?php
  function f0($numbers) {
    $mean = array_sum($numbers) / count($numbers);

    $sortedNumbers = $numbers;
    sort($sortedNumbers);
    $median;

    if(count($sortedNumbers) % 2 === 0) {
      $median = ($sortedNumbers[count($sortedNumbers) / 2 - 1] + $sortedNumbers[count($sortedNumbers) / 2]) / 2;
    } else {
      $median = $sortedNumbers[floor(count($sortedNumbers) / 2)];
    }

    return [$mean, $median];
  }


  function f1($numbers) {
    $mean = array_sum($numbers) / count($numbers);

    $sortedNumbers = $numbers;
    sort($sortedNumbers);
    $median;

    if(count($sortedNumbers) % 2 === 0) {
      $median = ($sortedNumbers[count($sortedNumbers) / 2 - 1] + $sortedNumbers[count($sortedNumbers) / 2]) / 2;
    } else {
      $median = $sortedNumbers[floor(count($sortedNumbers) / 2)];
    }

    return [$mean, $median];
  }
?>
