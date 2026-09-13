use std::collections::HashMap;

use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{Category, Issue, Level, Location, Range};
use regex::Regex;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
struct PhpstanOutput {
    totals: Totals,
    #[serde(default)]
    files: Option<Files>,
    errors: Vec<()>,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(untagged)]
enum Files {
    Map(HashMap<String, FileDetail>),
    Empty(Vec<()>),
}

#[derive(Serialize, Deserialize, Debug)]
struct Totals {
    errors: u32,
    file_errors: u32,
}

#[derive(Serialize, Deserialize, Debug)]
struct FileDetail {
    errors: u32,
    messages: Vec<Message>,
}

#[derive(Serialize, Deserialize, Debug)]
struct Message {
    message: String,
    line: u32,
    ignorable: bool,
    identifier: String,
    #[serde(default)]
    tip: Option<String>,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct Phpstan {}

impl Parser for Phpstan {
    fn parse(&self, _plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];
        let phpstan_output: PhpstanOutput = serde_json::from_str(output)?;

        if let Some(files) = phpstan_output.files {
            match files {
                Files::Map(map) => {
                    for (filename, detail) in map {
                        for message in detail.messages {
                            let issue = Issue {
                                tool: "phpstan".into(),
                                message: message.message,
                                category: Category::Lint.into(),
                                level: Level::Medium.into(),
                                rule_key: message.identifier,
                                documentation_url: message
                                    .tip
                                    .map(|s| extract_url(&s))
                                    .unwrap_or_default(),
                                location: Some(Location {
                                    path: filename.clone(),
                                    range: Some(Range {
                                        start_line: message.line,
                                        end_line: message.line,
                                        ..Default::default()
                                    }),
                                }),
                                ..Default::default()
                            };

                            issues.push(issue);
                        }
                    }
                }
                Files::Empty(_) => {} // Do nothing
            }
        }

        Ok(issues)
    }
}

fn extract_url(s: &str) -> String {
    // Extract URL from a string
    let url_regex = Regex::new(r"https?://[^\s]+").unwrap(); // Simple regex to match HTTP and HTTPS URLs
    match url_regex.find(s).map(|mat| mat.as_str().to_string()) {
        Some(url) => url,
        None => "".to_string(),
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"
        {
          "totals": { "errors": 0, "file_errors": 2 },
          "files": {
            "/code_climate/qlty/cli/qlty/tests/cmd/check/php.in/basic.in.php": {
              "errors": 2,
              "messages": [
                {
                  "message": "Parameter $date of method HelloWorld::sayHello() has invalid type DateTimeImutable.",
                  "line": 5,
                  "ignorable": true,
                  "identifier": "class.notFound"
                },
                {
                  "message": "Call to method format() on an unknown class DateTimeImutable.",
                  "line": 7,
                  "ignorable": true,
                  "tip": "Learn more at https://phpstan.org/user-guide/discovering-symbols",
                  "identifier": "class.notFound"
                }
              ]
            }
          },
          "errors": []
        }
        "###;

        let issues = Phpstan::default().parse("phpstan", input);
        insta::assert_yaml_snapshot!(issues.unwrap(), @r#"
        - tool: phpstan
          ruleKey: class.notFound
          message: "Parameter $date of method HelloWorld::sayHello() has invalid type DateTimeImutable."
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /code_climate/qlty/cli/qlty/tests/cmd/check/php.in/basic.in.php
            range:
              startLine: 5
              endLine: 5
        - tool: phpstan
          ruleKey: class.notFound
          message: Call to method format() on an unknown class DateTimeImutable.
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          documentationUrl: "https://phpstan.org/user-guide/discovering-symbols"
          location:
            path: /code_climate/qlty/cli/qlty/tests/cmd/check/php.in/basic.in.php
            range:
              startLine: 7
              endLine: 7
        "#);
    }

    #[test]
    fn parse_no_error() {
        let input = r###"
        {"totals":{"errors":0,"file_errors":0},"files":[],"errors":[]}
        "###;

        let issues = Phpstan::default().parse("phpstan", input);
        assert!(issues.unwrap().is_empty());
    }
}
