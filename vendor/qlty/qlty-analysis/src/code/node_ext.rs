use crate::Language;

pub trait NodeExt {
    fn is_if_statement_alternative(&self, language: &Box<dyn Language + Sync>) -> bool;
}

impl NodeExt for tree_sitter::Node<'_> {
    fn is_if_statement_alternative(&self, language: &Box<dyn Language + Sync>) -> bool {
        if let Some(parent) = self.parent() {
            if let Some(alternative) = parent.child_by_field_name("alternative") {
                return language.if_nodes().contains(&parent.kind()) && alternative == *self;
            }
        }

        false
    }
}
