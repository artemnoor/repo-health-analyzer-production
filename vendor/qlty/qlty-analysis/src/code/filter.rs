use crate::code::{File, QUERY_MATCH_LIMIT};
use crate::Language;
use anyhow::Context;
use std::sync::Arc;
use tree_sitter::{Node, Query, Range, Tree};

#[derive(Debug, Default, Clone)]
pub struct NodeFilter {
    ranges: Vec<Range>,
}

impl NodeFilter {
    pub fn empty() -> Self {
        Self::default()
    }

    pub fn add_range(&mut self, range: &Range) {
        if !self.contains_range(range) {
            self.ranges.push(range.to_owned());
        }
    }

    pub fn exclude(&self, node: &Node) -> bool {
        let range = node.range();
        self.contains_range(&range)
    }

    fn contains_range(&self, candidate: &Range) -> bool {
        self.ranges
            .iter()
            .any(|each| self.is_subrange(each, candidate))
    }

    fn is_subrange(&self, range: &Range, subrange: &Range) -> bool {
        subrange.start_byte >= range.start_byte && subrange.end_byte <= range.end_byte
    }
}

#[derive(Debug, Clone)]
pub struct NodeFilterBuilder {
    queries: Vec<Arc<Query>>,
}

impl NodeFilterBuilder {
    #[allow(clippy::borrowed_box)]
    pub fn for_patterns(language: &Box<dyn Language + Sync>, patterns: Vec<String>) -> Self {
        let queries = patterns
            .iter()
            .map(|pattern| {
                let query_with_capture = format!("{} @the-capture", pattern);
                let query = Query::new(&language.tree_sitter_language(), &query_with_capture)
                    .with_context(|| {
                        format!(
                            "Failed to parse {} query: {}",
                            language.name(),
                            &query_with_capture
                        )
                    });

                if query.is_err() {
                    query.as_ref().unwrap();
                }

                Arc::new(query.unwrap())
            })
            .collect();

        Self { queries }
    }

    pub fn build(&self, source_file: &File, tree: &Tree) -> NodeFilter {
        let mut filter = NodeFilter::empty();
        let node = tree.root_node();

        for query in self.queries.iter() {
            let mut cursor = tree_sitter::QueryCursor::new();
            cursor.set_match_limit(QUERY_MATCH_LIMIT as u32);

            let ranges: Vec<_> = cursor
                .matches(query, node, source_file.contents.as_bytes())
                .flat_map(|each_match| each_match.captures)
                .map(|capture| capture.node.range())
                .collect();

            for range in &ranges {
                filter.add_range(range);
            }
        }

        filter
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn none() {
        let source_file = File::from_string("javascript", "function foo() {}");
        let tree = source_file.parse();
        let filter = NodeFilter::empty();
        assert_eq!(false, filter.exclude(&tree.root_node()))
    }

    #[test]
    fn basic() {
        let language = crate::lang::from_str("javascript").unwrap();
        let patterns = vec!["(function_declaration)".to_string()];
        let builder = NodeFilterBuilder::for_patterns(language, patterns);

        let source_file = File::from_string("javascript", "function foo() {}");
        let tree = source_file.parse();

        let filter = builder.build(&source_file, &tree);
        insta::assert_debug_snapshot!(filter, @r"
        NodeFilter {
            ranges: [
                Range {
                    start_byte: 0,
                    end_byte: 17,
                    start_point: Point {
                        row: 0,
                        column: 0,
                    },
                    end_point: Point {
                        row: 0,
                        column: 17,
                    },
                },
            ],
        }
        ");
    }

    #[test]
    fn nested() {
        let language = crate::lang::from_str("javascript").unwrap();
        let patterns = vec!["(function_declaration)".to_string()];
        let builder = NodeFilterBuilder::for_patterns(language, patterns);

        let source_file = File::from_string("javascript", "function foo() { function bar() {}}");
        let tree = source_file.parse();

        let filter = builder.build(&source_file, &tree);
        insta::assert_debug_snapshot!(filter, @r"
        NodeFilter {
            ranges: [
                Range {
                    start_byte: 0,
                    end_byte: 35,
                    start_point: Point {
                        row: 0,
                        column: 0,
                    },
                    end_point: Point {
                        row: 0,
                        column: 35,
                    },
                },
            ],
        }
        ");
    }
}
