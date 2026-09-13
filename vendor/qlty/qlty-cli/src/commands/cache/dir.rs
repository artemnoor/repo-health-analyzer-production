use crate::{Arguments, CommandError, CommandSuccess};
use anyhow::Result;
use clap::Args;
use qlty_config::Workspace;

#[derive(Args, Debug)]
pub struct Dir {}

impl Dir {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        let workspace = Workspace::new()?;
        let library = workspace.library()?;
        println!("{}", library.cache_directory()?.display());
        CommandSuccess::ok()
    }
}
