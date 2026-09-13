use crate::ci::CI;

#[derive(Debug, Default)]
pub struct GitLab {}

impl CI for GitLab {
    fn detect(&self) -> bool {
        false // TODO
    }

    fn ci_name(&self) -> String {
        "GitLab".to_string()
    }

    fn ci_url(&self) -> String {
        "GitLab".to_string()
    }

    fn repository_name(&self) -> String {
        "".to_string()
    }

    fn repository_url(&self) -> String {
        "".to_string()
    }

    fn branch(&self) -> String {
        "master".to_string()
    }

    fn workflow(&self) -> String {
        "".to_string()
    }

    fn job(&self) -> String {
        "123".to_string()
    }

    fn build_id(&self) -> String {
        "123".to_string()
    }

    fn build_url(&self) -> String {
        "".to_string()
    }

    fn pull_number(&self) -> String {
        "".to_string()
    }

    fn pull_url(&self) -> String {
        "".to_string()
    }

    fn commit_sha(&self) -> String {
        "".to_string()
    }
}
