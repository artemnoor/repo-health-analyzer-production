use super::ActivePlugin;
use qlty_config::config::issue_transformer::IssueTransformer;
use qlty_types::analysis::v1::Issue;

#[derive(Debug, Clone)]
pub struct DocumentUrlGenerator {
    pub enabled_plugins: Vec<ActivePlugin>,
}

impl DocumentUrlGenerator {
    fn generate_document_url(issue_url_format: String, rule_key: String) -> String {
        issue_url_format.replace("${rule}", &rule_key)
    }
}

impl IssueTransformer for DocumentUrlGenerator {
    fn transform(&self, mut issue: Issue) -> Option<Issue> {
        if issue.documentation_url.is_empty() {
            if let Some(active_plugin) = self
                .enabled_plugins
                .iter()
                .find(|plugin| plugin.name == issue.tool)
            {
                if let Some(issue_url_format) = &active_plugin.plugin.issue_url_format {
                    issue.documentation_url = DocumentUrlGenerator::generate_document_url(
                        issue_url_format.clone(),
                        issue.rule_key.clone(),
                    );
                }
            }
        }
        Some(issue)
    }

    fn clone_box(&self) -> Box<dyn IssueTransformer> {
        Box::new(self.clone())
    }
}

#[cfg(test)]
mod test {
    use super::*;

    const RULE_KEY: &str = "rule-name";

    #[test]
    fn test_basic_replacement() {
        let issue_url_format = "https://example.com/rules/${rule}".to_string();
        let expected = "https://example.com/rules/rule-name".to_string();

        assert_eq!(
            DocumentUrlGenerator::generate_document_url(issue_url_format, RULE_KEY.to_string()),
            expected
        );
    }

    #[test]
    fn test_no_placeholder() {
        let issue_url_format = "https://example.com/rules".to_string();

        assert_eq!(
            DocumentUrlGenerator::generate_document_url(
                issue_url_format.clone(),
                RULE_KEY.to_string()
            ),
            issue_url_format
        );
    }
}
