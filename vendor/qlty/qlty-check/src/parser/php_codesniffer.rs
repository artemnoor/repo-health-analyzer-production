use std::collections::HashMap;

use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{Category, Issue, Level, Location, Range};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
struct PhpCodesnifferOutput {
    files: HashMap<String, FileDetail>,
}

#[derive(Serialize, Deserialize, Debug)]
struct FileDetail {
    messages: Vec<Message>,
}

#[derive(Serialize, Deserialize, Debug)]
struct Message {
    message: String,
    source: String,
    #[serde(rename = "type")]
    message_type: String,
    line: u32,
    column: u32,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct PhpCodesniffer {}

impl Parser for PhpCodesniffer {
    fn parse(&self, plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];
        let php_codesniffer_output: PhpCodesnifferOutput = serde_json::from_str(output)?;

        for (filename, detail) in php_codesniffer_output.files {
            for message in detail.messages {
                let issue = Issue {
                    tool: plugin_name.into(),
                    message: message.message,
                    category: Category::Lint.into(),
                    level: PhpCodesniffer::type_to_level(message.message_type).into(),
                    rule_key: message.source,
                    location: Some(Location {
                        path: filename.clone(),
                        range: Some(Range {
                            start_line: message.line,
                            start_column: message.column,
                            ..Default::default()
                        }),
                    }),
                    ..Default::default()
                };

                issues.push(issue);
            }
        }

        Ok(issues)
    }
}

impl PhpCodesniffer {
    fn type_to_level(message_type: String) -> Level {
        match message_type.as_str() {
            "ERROR" => Level::High,
            "WARNING" => Level::Medium,
            _ => Level::Low,
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"
        {
          "totals": { "errors": 11, "warnings": 0, "fixable": 8 },
          "files": {
            "/private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/basic.in.php": {
              "errors": 11,
              "warnings": 0,
              "messages": [
                {
                  "message": "Missing file doc comment",
                  "source": "PEAR.Commenting.FileComment.Missing",
                  "severity": 5,
                  "type": "ERROR",
                  "line": 2,
                  "column": 1,
                  "fixable": false
                },
                {
                  "message": "TRUE, FALSE and NULL must be lowercase; expected \"false\" but found \"FALSE\"",
                  "source": "Generic.PHP.LowerCaseConstant.Found",
                  "severity": 5,
                  "type": "ERROR",
                  "line": 4,
                  "column": 12,
                  "fixable": true
                },
                {
                  "message": "Line indented incorrectly; expected at least 4 spaces, found 1",
                  "source": "PEAR.WhiteSpace.ScopeIndent.Incorrect",
                  "severity": 5,
                  "type": "ERROR",
                  "line": 6,
                  "column": 2,
                  "fixable": true
                },
                {
                  "message": "Missing function doc comment",
                  "source": "PEAR.Commenting.FunctionComment.Missing",
                  "severity": 5,
                  "type": "ERROR",
                  "line": 9,
                  "column": 1,
                  "fixable": false
                },
                {
                  "message": "Inline control structures are discouraged",
                  "source": "Generic.ControlStructures.InlineControlStructure.Discouraged",
                  "severity": 5,
                  "type": "WARNING",
                  "line": 11,
                  "column": 5,
                  "fixable": true
                }
              ]
            },
            "/private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/second.in.php": {
              "errors": 0,
              "warnings": 0,
              "messages": [

              ]
            }
          }
        }
        "###;

        let issues = PhpCodesniffer::default().parse("php_codesniffer", input);
        insta::assert_yaml_snapshot!(issues.unwrap(), @r#"
        - tool: php_codesniffer
          ruleKey: PEAR.Commenting.FileComment.Missing
          message: Missing file doc comment
          level: LEVEL_HIGH
          category: CATEGORY_LINT
          location:
            path: /private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/basic.in.php
            range:
              startLine: 2
              startColumn: 1
        - tool: php_codesniffer
          ruleKey: Generic.PHP.LowerCaseConstant.Found
          message: "TRUE, FALSE and NULL must be lowercase; expected \"false\" but found \"FALSE\""
          level: LEVEL_HIGH
          category: CATEGORY_LINT
          location:
            path: /private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/basic.in.php
            range:
              startLine: 4
              startColumn: 12
        - tool: php_codesniffer
          ruleKey: PEAR.WhiteSpace.ScopeIndent.Incorrect
          message: "Line indented incorrectly; expected at least 4 spaces, found 1"
          level: LEVEL_HIGH
          category: CATEGORY_LINT
          location:
            path: /private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/basic.in.php
            range:
              startLine: 6
              startColumn: 2
        - tool: php_codesniffer
          ruleKey: PEAR.Commenting.FunctionComment.Missing
          message: Missing function doc comment
          level: LEVEL_HIGH
          category: CATEGORY_LINT
          location:
            path: /private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/basic.in.php
            range:
              startLine: 9
              startColumn: 1
        - tool: php_codesniffer
          ruleKey: Generic.ControlStructures.InlineControlStructure.Discouraged
          message: Inline control structures are discouraged
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /private/var/folders/b9/flqsg2gj0zs94d9802z004qw0000gn/T/plugins_TTkQo6/basic.in.php
            range:
              startLine: 11
              startColumn: 5
        "#);
    }
}
