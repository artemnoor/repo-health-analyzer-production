use std::path::PathBuf;

#[derive(Debug, Default, Clone)]
pub struct Settings {
    pub paths: Vec<PathBuf>,
    pub include_tests: bool,
}

impl Settings {
    pub fn include_tests(&mut self, include_tests: bool) -> &mut Self {
        self.include_tests = include_tests;
        self
    }
}
