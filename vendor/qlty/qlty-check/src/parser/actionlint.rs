use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{Category, Issue, Level, Location, Range};
use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct ActionlintFile {
    pub message: String,
    pub filepath: String,
    pub line: u64,
    pub column: u64,
    pub kind: String,
    pub end_column: u64,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct Actionlint {}

impl Parser for Actionlint {
    fn parse(&self, _plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];
        let actionlint_issues: Vec<ActionlintFile> = serde_json::from_str(output)?;

        for issue in actionlint_issues {
            let location = Some(Location {
                path: issue.filepath.clone(),
                range: Some(Range {
                    start_line: issue.line as u32,
                    start_column: issue.column as u32,
                    end_line: issue.line as u32,
                    end_column: issue.end_column as u32,
                    ..Default::default()
                }),
            });

            let issue = Issue {
                tool: "actionlint".to_string(),
                rule_key: issue.kind,
                message: issue.message,
                category: Category::Lint.into(),
                level: Level::Medium.into(),
                location,
                ..Default::default()
            };

            issues.push(issue);
        }

        Ok(issues)
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"
        [
        {
            "message": "invalid CRON format \"0 */3 * *\" in schedule event: expected exactly 5 fields, found 4: [0 */3 * *]",
            "filepath": "bad.in.yaml",
            "line": 4,
            "column": 13,
            "kind": "events",
            "snippet": "    - cron: '0 */3 * *'\n            ^~",
            "end_column": 14
        },
        {
            "message": "scheduled job runs too frequently. it runs once per 60 seconds. the shortest interval is once every 5 minutes",
            "filepath": "bad.in.yaml",
            "line": 6,
            "column": 13,
            "kind": "events",
            "snippet": "    - cron: '* */3 * * *'\n            ^~",
            "end_column": 14
        },
        {
            "message": "workflow is empty",
            "filepath": "empty.in.yaml",
            "line": 1,
            "column": 1,
            "kind": "syntax-check",
            "end_column": 1
        }
        ]
        "###;

        let issues = Actionlint::default().parse("actionlint", input);
        insta::assert_yaml_snapshot!(issues.unwrap(), @r#"
        - tool: actionlint
          ruleKey: events
          message: "invalid CRON format \"0 */3 * *\" in schedule event: expected exactly 5 fields, found 4: [0 */3 * *]"
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: bad.in.yaml
            range:
              startLine: 4
              startColumn: 13
              endLine: 4
              endColumn: 14
        - tool: actionlint
          ruleKey: events
          message: scheduled job runs too frequently. it runs once per 60 seconds. the shortest interval is once every 5 minutes
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: bad.in.yaml
            range:
              startLine: 6
              startColumn: 13
              endLine: 6
              endColumn: 14
        - tool: actionlint
          ruleKey: syntax-check
          message: workflow is empty
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: empty.in.yaml
            range:
              startLine: 1
              startColumn: 1
              endLine: 1
              endColumn: 1
        "#);
    }
}
