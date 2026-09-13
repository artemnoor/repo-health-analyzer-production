use qlty_analysis::code::File;
use qlty_config::config::issue_transformer::IssueTransformer;
use qlty_config::config::IssueMode;
use std::{collections::HashMap, sync::Arc};

#[derive(Clone, Debug)]
pub struct Plan {
    pub languages: HashMap<String, LanguagePlan>,
    pub source_files: Vec<Arc<File>>,
    pub transformers: Vec<Box<dyn IssueTransformer>>,
}

impl Plan {
    pub fn get_language(&self, language: &str) -> LanguagePlan {
        self.languages
            .get(language)
            .unwrap_or(&LanguagePlan::default())
            .clone()
    }
}

#[derive(Clone, Debug, Default)]
pub struct LanguagePlan {
    pub filters: Vec<String>,
    pub nodes_threshold: usize,
    pub identical_lines_threshold: Option<usize>,
    pub similar_lines_threshold: Option<usize>,
    pub issue_mode: IssueMode,
}
