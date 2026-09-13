benchmarkClass() {
  if (ptile === null) {
    return null
  } else if (ptile >= 95) {
    return "heatmap--top-5"
  } else if (ptile >= 90) {
    return "heatmap--top-10"
  } else if (ptile >= 75) {
    return "heatmap--top-25"
  } else if (ptile >= 25) {
    return null
  } else if (ptile >= 10) {
    return "heatmap--bottom-25"
  } else if (ptile >= 5) {
    return "heatmap--bottom-10"
  } else if (ptile >= 0) {
    return "heatmap--bottom-5"
  }
}
