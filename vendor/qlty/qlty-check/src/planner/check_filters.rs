use crate::CheckFilter;
use qlty_config::config::issue_transformer::IssueTransformer;
use qlty_types::analysis::v1::Issue;

#[derive(Debug, Clone)]
pub struct CheckFilters {
    pub filters: Vec<CheckFilter>,
}

impl IssueTransformer for CheckFilters {
    fn transform(&self, issue: Issue) -> Option<Issue> {
        if self.filters.is_empty() {
            return Some(issue);
        }

        if self
            .filters
            .iter()
            .any(|filter| filter.matches_issue(&issue))
        {
            Some(issue)
        } else {
            None
        }
    }

    fn clone_box(&self) -> Box<dyn IssueTransformer> {
        Box::new(self.clone())
    }
}
