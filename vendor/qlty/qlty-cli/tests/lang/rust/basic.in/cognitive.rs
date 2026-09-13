fn f0(foo: Option<i32>) -> Option<&'static str> {
    match foo {
        // +1 (for match statement)
        Some(value) if value >= 80 && value <= 100 => {
            // +1 (for the &&)
            Some("Most complex!")
        }
        Some(value) if value >= 60 && value <= 79 => {
            // +1 (for the &&)
            Some("Very complex")
        }
        Some(value) if value >= 40 && value <= 59 => {
            // +1 (for the &&)
            Some("Somewhat complex")
        }
        Some(value) if value >= 20 && value <= 39 => {
            // +1 (for the &&)
            Some("Not complex")
        }
        Some(value) if value >= 0 && value <= 19 => {
            // +1 (for the &&)
            Some("Least complex!")
        }
        None => None,
        _ => None,
    }
}

// count_non_sequential_logical_operators_rust
fn f2() -> bool {
    true || false && true && false || true
}

// // fixing the `visit_binary` node traversal broke this test
// // it now treats each `&&` as sequential, even though they're not
// // since they're broken up by different `match_arm` nodes
// // we previously just counted _every_ binary operator, which was incorrect
// // but gave us the correct answer based on how the test is structured
// fn how_complex(foo: Option<i32>) -> Option<&'static str> {
//   match foo {                                            // +1 (for match statement)
//       Some(value) if value >= 80 && value <= 100 => {    // +1 (for the &&)
//           Some("Most complex!")
//       },
//       Some(value) if value >= 60 && value <= 79 => {     // +1 (for the &&)
//           Some("Very complex")
//       },
//       Some(value) if value >= 40 && value <= 59 => {     // +1 (for the &&)
//           Some("Somewhat complex")
//       },
//       Some(value) if value >= 20 && value <= 39 => {     // +1 (for the &&)
//           Some("Not complex")
//       },
//       Some(value) if value >= 0 && value <= 19 => {      // +1 (for the &&)
//           Some("Least complex!")
//       },
//       None => {
//           None
//       },
//       _ => {
//           None
//       },
//   }
// }
