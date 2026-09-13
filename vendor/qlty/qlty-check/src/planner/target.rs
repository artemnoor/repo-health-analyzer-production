use crate::executor::staging_area::StagingArea;
use anyhow::{anyhow, bail, Result};
use itertools::Itertools;
use qlty_analysis::{WorkspaceEntry, WorkspaceEntryKind};
use qlty_config::config::{TargetDef, TargetType};
use std::{collections::HashSet, path::PathBuf};
use tracing::debug;

#[derive(Debug)]
pub struct TargetFinder {
    staging_area: StagingArea,
    target_def: TargetDef,
}

pub type Target = WorkspaceEntry;

impl TargetFinder {
    pub fn new(staging_area: StagingArea, target_def: TargetDef) -> Self {
        Self {
            staging_area,
            target_def,
        }
    }

    fn find_file_or_folder(&self, workspace_entry: &WorkspaceEntry) -> Option<PathBuf> {
        let starting_path = self
            .staging_area
            .source_directory
            .join(workspace_entry.path.clone());
        let mut current_path = starting_path.to_path_buf();

        // Loop until the root of the directory structure is reached
        loop {
            let potential_target =
                current_path.join(self.target_def.path.clone().unwrap().as_str());

            if std::fs::metadata(&potential_target).is_ok() {
                return Some(potential_target);
            }

            // Move to the parent directory, if possible
            if current_path == self.staging_area.source_directory || !current_path.pop() {
                break;
            }
        }

        None
    }

    pub fn resolve_target_for_entry(
        &self,
        workspace_entry: &WorkspaceEntry,
    ) -> Result<Option<Target>> {
        match self.target_def.target_type {
            TargetType::File => {
                let target: Target = workspace_entry.clone();
                Ok(Some(target))
            }
            TargetType::Literal => {
                let mut target: Target = workspace_entry.clone();
                target.path = self
                    .target_def
                    .path
                    .clone()
                    .ok_or(anyhow!("Target path is required for target type 'literal'"))?
                    .into();
                target.kind = WorkspaceEntryKind::Directory;
                Ok(Some(target))
            }
            TargetType::ParentWith => match self.find_file_or_folder(workspace_entry) {
                Some(found_path) => {
                    let mut target: Target = workspace_entry.clone();
                    let relative_path = found_path
                        .strip_prefix(&self.staging_area.source_directory)
                        .unwrap_or(&found_path);

                    target.path = relative_path
                        .parent()
                        .ok_or(anyhow!(
                            "Could not find parent directory for target: {:?}",
                            relative_path
                        ))?
                        .to_path_buf();
                    target.kind = WorkspaceEntryKind::Directory;

                    Ok(Some(target))
                }
                None => {
                    debug!(
                        "Could not find target for workspace entry: {:?}",
                        workspace_entry
                    );
                    Ok(None)
                }
            },
            TargetType::Parent => {
                let mut target: Target = workspace_entry.clone();
                target.path = workspace_entry.path.parent().unwrap().to_path_buf();
                target.kind = WorkspaceEntryKind::Directory;

                Ok(Some(target))
            }
        }
    }

    pub fn find(&self, workspace_entries: &[WorkspaceEntry]) -> Result<Vec<Target>> {
        let targets_results = workspace_entries
            .iter()
            .map(|workspace_entry| self.resolve_target_for_entry(workspace_entry))
            .collect_vec();

        let mut targets = vec![];

        for target_result in targets_results {
            match target_result {
                Ok(Some(target)) => targets.push(target),
                Ok(None) => {}
                Err(err) => {
                    bail!("Error while resolving target: {:?}", err);
                }
            }
        }

        let mut unique_paths = HashSet::new();
        let mut unique_targets = Vec::new();

        for target in targets {
            if unique_paths.insert(target.path.clone()) {
                unique_targets.push(target);
            }
        }

        Ok(unique_targets)
    }
}
