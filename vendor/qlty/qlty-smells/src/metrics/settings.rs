use qlty_analysis::workspace_entries::TargetMode;
use std::fmt;

#[derive(Debug, Clone, Default)]
pub struct Settings {
    pub functions: bool,
    pub target_mode: TargetMode,
    pub exclude_tests: bool,
}

#[derive(Debug, Clone, Copy)]
pub enum MetricsMode {
    Files,
    Functions,
}

impl Default for MetricsMode {
    fn default() -> Self {
        Self::Files
    }
}
impl fmt::Display for MetricsMode {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            MetricsMode::Files => write!(f, "files"),
            MetricsMode::Functions => write!(f, "functions"),
        }
    }
}
