use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{Category, Issue, Level, Location, Range};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RubocopJson {
    pub files: Vec<RubocopFile>,
    metadata: Option<serde_json::Value>,
    summary: Option<serde_json::Value>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RubocopFile {
    pub path: String,
    pub offenses: Vec<RubocopOffense>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RubocopOffense {
    pub severity: String,
    pub message: String,
    pub cop_name: String,
    pub corrected: bool,
    pub correctable: Option<bool>,
    pub location: RubocopLocation,
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy)]
pub struct RubocopLocation {
    pub start_line: i32,
    pub start_column: i32,
    pub last_line: i32,
    pub last_column: i32,
    pub length: i32,
    pub line: i32,
    pub column: i32,
}

#[derive(Debug, Default)]
pub struct Rubocop {}

impl Parser for Rubocop {
    fn parse(&self, plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];

        for file in serde_json::from_str::<RubocopJson>(output)?.files {
            for offense in file.offenses {
                let issue = Issue {
                    tool: plugin_name.into(),
                    message: offense.message.trim().to_string(),
                    category: cop_name_to_category(&offense.cop_name).into(),
                    level: severity_to_level(&offense.severity).into(),
                    rule_key: offense.cop_name,
                    location: Some(Location {
                        path: file.path.clone(),
                        range: Some(Range {
                            start_line: offense.location.start_line as u32,
                            start_column: offense.location.start_column as u32,
                            end_line: offense.location.last_line as u32,
                            end_column: offense.location.last_column as u32,
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

fn cop_name_to_category(cop_name: &str) -> Category {
    if cop_name.to_lowercase().starts_with("layout") || cop_name.to_lowercase().starts_with("style")
    {
        Category::Style
    } else if cop_name.to_lowercase().starts_with("performance") {
        Category::Performance
    } else {
        Category::Lint
    }
}

fn severity_to_level(severity: &str) -> Level {
    match severity {
        "fatal" => Level::High,
        "error" => Level::High,
        "warning" => Level::Medium,
        "refactor" => Level::Medium,
        "info" => Level::Low,
        "convention" => Level::Medium,
        _ => Level::Low,
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"{
          "metadata": {
            "rubocop_version": "1.39.0",
            "ruby_engine": "ruby",
            "ruby_version": "3.2.0",
            "ruby_patchlevel": "0",
            "ruby_platform": "aarch64-linux-musl"
          },
          "files": [
            {
              "path": "/usr/local/bundle/gems/rubocop-1.39.0/lib/rubocop.rb",
              "offenses": [
                {
                  "severity": "warning",
                  "message": "Unnecessary disabling of `Naming/InclusiveLanguage`.",
                  "cop_name": "Lint/RedundantCopDisableDirective",
                  "corrected": false,
                  "correctable": true,
                  "location": {
                    "start_line": 68,
                    "start_column": 53,
                    "last_line": 68,
                    "last_column": 91,
                    "length": 39,
                    "line": 68,
                    "column": 53
                  }
                }
              ]
            }
          ],
          "summary": {
            "offense_count": 1,
            "target_file_count": 1,
            "inspected_file_count": 1
          }
        }"###;

        let issues = Rubocop {}.parse("rubocop", input);
        insta::assert_yaml_snapshot!(issues.unwrap(), @r#"
        - tool: rubocop
          ruleKey: Lint/RedundantCopDisableDirective
          message: "Unnecessary disabling of `Naming/InclusiveLanguage`."
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /usr/local/bundle/gems/rubocop-1.39.0/lib/rubocop.rb
            range:
              startLine: 68
              startColumn: 53
              endLine: 68
              endColumn: 91
        "#);
    }
}
