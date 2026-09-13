use crate::{errors::CommandError, success::CommandSuccess, Arguments};
use anyhow::Result;
use clap::Args;

#[derive(Args, Debug)]
pub struct Docs {}

impl Docs {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        webbrowser::open("https://qlty.sh/docs")?;
        CommandSuccess::ok()
    }
}
