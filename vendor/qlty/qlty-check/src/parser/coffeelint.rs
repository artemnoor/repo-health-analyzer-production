use std::collections::HashMap;

use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{Category, Issue, Level, Location, Range};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Clone)]
struct CoffeelintIssue {
    #[serde(rename = "type")]
    issue_type: String,
    level: String,
    message: String,
    #[serde(rename = "lineNumber")]
    line_number: u32,
    #[serde(rename = "columnNumber")]
    column_number: Option<u32>,
    #[serde(rename = "lineNumberEnd")]
    line_number_end: Option<u32>,
    #[serde(rename = "columnNumberEnd")]
    column_number_end: Option<u32>,
    rule: String,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct Coffeelint {}

impl Parser for Coffeelint {
    fn parse(&self, plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];
        let coffeelint_output: HashMap<String, Vec<CoffeelintIssue>> =
            serde_json::from_str(output)?;

        for (filename, coffeelint_issues) in coffeelint_output {
            for coffeelint_issue in coffeelint_issues {
                let issue = Issue {
                    tool: plugin_name.into(),
                    message: coffeelint_issue.message,
                    category: type_to_category(coffeelint_issue.issue_type).into(),
                    level: coffelint_level_to_issue_level(coffeelint_issue.level).into(),
                    rule_key: coffeelint_issue.rule,
                    location: Some(Location {
                        path: filename.clone(),
                        range: Some(Range {
                            start_line: coffeelint_issue.line_number,
                            start_column: coffeelint_issue.column_number.unwrap_or(1),
                            end_line: coffeelint_issue
                                .line_number_end
                                .unwrap_or(coffeelint_issue.line_number),
                            end_column: coffeelint_issue.column_number_end.unwrap_or(1),
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

fn coffelint_level_to_issue_level(severity: String) -> Level {
    match severity.as_str() {
        "ignore" => Level::Low,
        "warn" => Level::Medium,
        "error" => Level::High,
        _ => Level::Medium,
    }
}

fn type_to_category(issue_type: String) -> Category {
    // there are two types "style" and "problem"
    match issue_type.as_str() {
        "style" => Category::Style,
        _ => Category::Lint,
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"
        {
    "second.coffee": [
      {
        "type": "problem",
        "name": "missing_parseint_radix",
        "level": "warn",
        "message": "parseInt is missing the radix argument",
        "description": "This rule warns about using parseInt without a radix. From the MDN\ndevelopers reference: <q>Always specify this parameter to eliminate\nreader confusion and to guarantee predictable behavior.</q>\n<pre>\n  <code># You would expect this to result in 8, but\n  # it might result in 0 (parsed as octal).\n  parseInt '08'\n\n  # To be safe, specify the radix argument:\n  parseInt '08', 10\n  </code>\n</pre>",
        "token": [
          "CALL_START",
          "(",
          {
            "first_line": 2,
            "first_column": 8,
            "last_line": 2,
            "last_column": 8,
            "last_line_exclusive": 2,
            "last_column_exclusive": 8,
            "range": [
              94,
              94
            ]
          }
        ],
        "lineNumber": 3,
        "line": "parseInt '08'",
        "columnNumber": 9,
        "lineNumberEnd": 3,
        "columnNumberEnd": 9,
        "rule": "missing_parseint_radix"
      },
      {
        "type": "problem",
        "name": "no_throwing_strings",
        "level": "error",
        "message": "Throwing strings is forbidden",
        "description": "This rule forbids throwing string literals or interpolations. While\nJavaScript (and CoffeeScript by extension) allow any expression to\nbe thrown, it is best to only throw <a\nhref=\"https://developer.mozilla.org\n/en/JavaScript/Reference/Global_Objects/Error\"> Error</a> objects,\nbecause they contain valuable debugging information like the stack\ntrace. Because of JavaScript's dynamic nature, CoffeeLint cannot\nensure you are always throwing instances of <tt>Error</tt>. It will\nonly catch the simple but real case of throwing literal strings.\n<pre>\n<code># CoffeeLint will catch this:\nthrow \"i made a boo boo\"\n\n# ... but not this:\nthrow getSomeString()\n</code>\n</pre>\nThis rule is enabled by default.",
        "token": [
          "THROW",
          "throw",
          {
            "range": [
              193,
              198
            ],
            "first_line": 9,
            "first_column": 0,
            "last_line": 9,
            "last_column": 4,
            "last_line_exclusive": 9,
            "last_column_exclusive": 5
          }
        ],
        "lineNumber": 10,
        "line": "throw \"i made a boo boo\"",
        "columnNumber": 1,
        "lineNumberEnd": 10,
        "columnNumberEnd": 5,
        "rule": "no_throwing_strings"
      }
    ]
  }
        "###;

        let issues = Coffeelint::default().parse("coffeelint", input);
        insta::assert_yaml_snapshot!(issues.unwrap(), @r"
        - tool: coffeelint
          ruleKey: missing_parseint_radix
          message: parseInt is missing the radix argument
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: second.coffee
            range:
              startLine: 3
              startColumn: 9
              endLine: 3
              endColumn: 9
        - tool: coffeelint
          ruleKey: no_throwing_strings
          message: Throwing strings is forbidden
          level: LEVEL_HIGH
          category: CATEGORY_LINT
          location:
            path: second.coffee
            range:
              startLine: 10
              startColumn: 1
              endLine: 10
              endColumn: 5
        ");
    }
}
