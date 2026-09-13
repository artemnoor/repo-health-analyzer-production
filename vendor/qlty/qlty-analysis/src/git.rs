mod diff;
mod upstream;

pub use diff::{DiffLineFilter, DiffMode, GitDiff};
pub use upstream::compute_upstream;
