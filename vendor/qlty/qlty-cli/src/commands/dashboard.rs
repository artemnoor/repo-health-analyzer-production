use crate::{errors::CommandError, success::CommandSuccess, Arguments};
use anyhow::Result;
use clap::Args;

#[derive(Args, Debug)]
pub struct Dashboard {}

impl Dashboard {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        webbrowser::open("https://qlty.sh/dashboard")?;
        CommandSuccess::ok()
    }
}
