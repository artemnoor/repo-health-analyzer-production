use crate::lang::Language;
use crate::WorkspaceEntry;
use anyhow::{anyhow, Result};
use md5::Digest;
use serde::Serialize;
use std::path::PathBuf;
use std::sync::Arc;
use tree_sitter::Tree;

#[derive(Debug, Clone, Eq, PartialEq, Hash, Serialize)]
pub struct File {
    pub language_name: String,
    pub path: PathBuf,
    pub contents: String,

    #[serde(with = "DigestDef")]
    pub digest: Digest,
}

#[derive(Serialize)]
#[serde(remote = "Digest")]
pub struct DigestDef(pub [u8; 16]);

impl File {
    pub fn from_workspace_entry(workspace_entry: &WorkspaceEntry) -> Result<Arc<Self>> {
        match workspace_entry.language_name {
            Some(ref language_name) => Self::from_path(language_name, &workspace_entry.path),
            None => Err(anyhow!(
                "Failed to determine language for the file {}",
                workspace_entry.path.display()
            )),
        }
    }

    pub fn from_path<P: Into<PathBuf>>(language_name: &str, path: P) -> Result<Arc<Self>> {
        let path = path.into();

        let contents = match std::fs::read_to_string(&path) {
            Ok(content) => content,
            Err(e) => {
                return Err(anyhow!(
                    "Failed to read file from path {}: {}",
                    path.display(),
                    e
                ))
            }
        };

        let digest = md5::compute(&contents);

        Ok(Arc::new(Self {
            path,
            contents,
            digest,
            language_name: language_name.to_string(),
        }))
    }

    pub fn from_string(language_name: &str, contents: &str) -> Self {
        Self {
            path: PathBuf::from("STRING"),
            contents: contents.to_string(),
            digest: md5::compute(contents),
            language_name: language_name.to_string(),
        }
    }

    pub fn query(&self, query_source: &str) -> tree_sitter::Query {
        self.language().query(query_source)
    }

    #[allow(clippy::borrowed_box)]
    pub fn language(&self) -> &Box<dyn Language + Sync> {
        crate::lang::from_str(&self.language_name).unwrap()
    }

    pub fn parse(&self) -> Tree {
        let mut parser = self.language().parser();
        parser.parse(self.contents.clone(), None).unwrap()
    }
}
