use console::style;
use indicatif::ProgressStyle;
use std::time::Duration;

pub trait ProgressBar: Clone {
    fn set_prefix(&self, message: &str) {
        self.bar().set_prefix(message.to_owned());
    }

    fn set_message(&self, message: &str) {
        self.bar().set_message(message.to_owned());
    }

    fn set_dim_message(&self, message: &str) {
        let styled_message = format!("{}", style(message).dim());
        self.set_message(&styled_message);
    }

    fn increment(&self, n: u64) {
        self.bar().inc(n);
    }

    fn clear(&self) {
        self.bar().finish_and_clear();
    }

    fn bar(&self) -> &indicatif::ProgressBar;
}

#[derive(Debug, Clone)]
pub struct Progress {
    multi: indicatif::MultiProgress,
    main: indicatif::ProgressBar,
}

impl Progress {
    pub fn new(enabled: bool, increments: u64) -> Self {
        Self::new_with_style(enabled, increments, main_spinner_without_position_style())
    }

    pub fn new_with_position(enabled: bool, increments: u64) -> Self {
        Self::new_with_style(enabled, increments, main_spinner_with_position_style())
    }

    fn new_with_style(enabled: bool, increments: u64, main_style: ProgressStyle) -> Self {
        let multi = indicatif::MultiProgress::new();

        if !enabled {
            multi.set_draw_target(indicatif::ProgressDrawTarget::hidden());
        }

        let main = multi.add(indicatif::ProgressBar::new(increments).with_style(main_style));
        main.enable_steady_tick(Duration::new(0, 250000));

        Self { multi, main }
    }

    pub fn task(&self, prefix: &str, message: &str) -> ProgressTask {
        let task_progress = self.multi.add(indicatif::ProgressBar::new(1));
        task_progress.set_style(task_spinner_style());

        task_progress.enable_steady_tick(Duration::new(0, 100000));
        task_progress.set_prefix(prefix.to_owned());
        task_progress.set_message(message.to_owned());

        ProgressTask {
            progress: self.clone(),
            bar: task_progress,
        }
    }
}

impl ProgressBar for Progress {
    fn bar(&self) -> &indicatif::ProgressBar {
        &self.main
    }
}

#[derive(Debug, Clone)]
pub struct ProgressTask {
    progress: Progress,
    bar: indicatif::ProgressBar,
}

impl ProgressBar for ProgressTask {
    fn increment(&self, n: u64) {
        self.progress.increment(n);
    }

    fn bar(&self) -> &indicatif::ProgressBar {
        &self.bar
    }
}

fn main_spinner_with_position_style() -> indicatif::ProgressStyle {
    indicatif::ProgressStyle::with_template(
        "{prefix:.cyan.bold}  {percent}% [{wide_bar}]  {pos}/{len}  {elapsed_precise}",
    )
    .unwrap()
    .progress_chars("=> ")
}

fn main_spinner_without_position_style() -> indicatif::ProgressStyle {
    indicatif::ProgressStyle::with_template(
        "{prefix:.cyan.bold}  {percent}% [{wide_bar}]  {elapsed_precise}",
    )
    .unwrap()
    .progress_chars("=> ")
}

fn task_spinner_style() -> indicatif::ProgressStyle {
    indicatif::ProgressStyle::with_template(" ∟ {prefix:.bold.dim} {msg} {spinner}")
        .unwrap()
        .tick_chars("⠁⠂⠄⡀⢀⠠⠐⠈ ")
}
