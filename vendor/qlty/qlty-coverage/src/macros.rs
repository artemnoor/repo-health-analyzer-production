#[macro_export]
macro_rules! eprintln_unless {
    ($cond:expr, $($arg:tt)*) => {
        if !$cond {
            eprintln!($($arg)*);
        }
    };
}
