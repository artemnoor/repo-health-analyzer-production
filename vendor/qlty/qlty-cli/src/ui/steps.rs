use console::{style, Emoji};
use std::time::Instant;

pub struct Steps {
    quiet: bool,
    timer: Instant,
    current: usize,
    total: usize,
}

impl Steps {
    pub fn new(quiet: bool, total: usize) -> Self {
        Self {
            quiet,
            total,
            current: 0,
            timer: Instant::now(),
        }
    }

    pub fn start<S: Into<String>>(&mut self, emoji: Emoji, message: S) {
        if !self.quiet {
            if self.current > 0 {
                let duration = self.timer.elapsed();
                self.timer = Instant::now();
                eprintln!("{:.2}s", duration.as_secs_f32());
            }

            eprint!(
                "{:>10} {}{} ",
                style(format!("[{}/{}]", self.current, self.total))
                    .bold()
                    .dim(),
                emoji,
                message.into()
            );
        }

        self.current += 1;
    }
}
